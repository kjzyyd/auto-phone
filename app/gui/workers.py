"""后台工作线程：设备连接 / 豆包服务 / Agent 执行。"""
from __future__ import annotations

import queue
import threading
import time

from PySide6.QtCore import QThread, Signal

from ..core.agent import AgentCallbacks, PhoneAgent
from ..core.config import Config
from ..core.device.controller import DeviceController
from ..core.doubao import DoubaoClient


# ---------------- 设备连接 ----------------
class DeviceWorker(QThread):
    connected = Signal(object)   # DeviceInfo
    failed = Signal(str)
    log = Signal(str, str)

    def __init__(self, device: DeviceController, serial: str | None, parent=None):
        super().__init__(parent)
        self.device = device
        self.serial = serial

    def run(self) -> None:
        try:
            info = self.device.connect(self.serial)
            self.connected.emit(info)
        except Exception as e:  # noqa: BLE001
            self.failed.emit(str(e))


# ---------------- 豆包服务（单线程持有 Playwright） ----------------
class DoubaoWorker(QThread):
    started = Signal()
    login_changed = Signal(bool)   # 是否已登录（输入框可见）
    reply_ready = Signal(str)
    ask_failed = Signal(str)
    log = Signal(str, str)
    closed = Signal()

    def __init__(self, config: Config, parent=None):
        super().__init__(parent)
        self.config = config
        self.client: DoubaoClient | None = None
        self._q: "queue.Queue[tuple]" = queue.Queue()
        self._reply_box: dict = {}
        self._reply_ev: dict = {}
        self._closed = threading.Event()

    # ---------- 供 GUI / Agent 调用的线程安全接口 ----------
    def request_start(self) -> None:
        self._q.put(("start",))

    def request_check_login(self) -> None:
        self._q.put(("check_login",))

    def ask(self, instruction: str, image: bytes | None = None, timeout: int = 180) -> str:
        """阻塞等待豆包回复（与 DoubaoClient.ask 鸭子接口一致，供 Agent 线程调用）。"""
        key = f"ask-{threading.get_ident()}-{time.time():.3f}"
        ev = threading.Event()
        self._reply_box[key] = {"result": None, "error": None}
        self._reply_ev[key] = ev
        self._q.put(("ask", key, instruction, image, timeout))
        ev.wait(timeout + 30)
        holder = self._reply_box.pop(key, {})
        self._reply_ev.pop(key, None)
        if holder.get("error"):
            raise RuntimeError(holder["error"])
        return holder.get("result") or ""

    def ask_sync(self, instruction: str, image: bytes | None, timeout: int) -> str:
        """ask 的旧别名，向后兼容。"""
        return self.ask(instruction, image=image, timeout=timeout)

    def request_close(self) -> None:
        self._q.put(("close",))

    # ---------- 线程主体 ----------
    def run(self) -> None:
        # 登录轮询：
        #   - 未登录 → 每 1.2s 检查一次；成功检测 → login_changed(True) 并改为低频（15s）。
        #   - 已登录 → 低频（15s）复查一次，防止 cookie 过期掉线后 UI 状态错误。
        #   - 用户可随时发 request_check_login 手动触发（返回 True/False 都发一次 login_changed）。
        last_check_ts = 0.0
        fast_interval = 1.2
        slow_interval = 15.0
        last_login_state: bool | None = None

        def _apply_login_state(ok: bool) -> None:
            nonlocal last_login_state
            if ok != last_login_state:
                last_login_state = ok
                self.login_changed.emit(ok)

        while not self._closed.is_set():
            now = time.time()
            interval = slow_interval if last_login_state else fast_interval
            do_check = False
            if last_check_ts <= 0 or now - last_check_ts >= interval:
                do_check = True
                last_check_ts = now

            try:
                cmd = self._q.get(timeout=0.25)
            except queue.Empty:
                if do_check and self.client is not None:
                    try:
                        ok = bool(self.client.is_logged_in())
                        _apply_login_state(ok)
                    except Exception:
                        pass
                continue
            kind = cmd[0]
            try:
                if kind == "start":
                    self.client = DoubaoClient(self.config, self._emit_log)
                    self.client.ensure_browser()
                    self.client.start()
                    self.started.emit()
                    last_check_ts = now  # 刚启动，等一个 interval 再首次轮询
                    last_login_state = None
                elif kind == "check_login":
                    ok, reason = False, ""
                    try:
                        if self.client:
                            r = self.client.is_logged_in(with_reason=True)
                            if isinstance(r, tuple):
                                ok = bool(r[0])
                                reason = str(r[1])
                            else:
                                ok = bool(r)
                                reason = "已登录" if ok else "未登录"
                    except Exception as e:
                        ok, reason = False, f"登录检测异常：{e}"
                    _apply_login_state(ok)
                    # 原因写操作日志，方便用户对着每一条去排查
                    if reason:
                        tag = "success" if ok else "warn"
                        self._emit_log("【登录检测】\n" + reason, tag)
                elif kind == "ask":
                    _, key, instr, image, timeout = cmd
                    holder = self._reply_box.get(key)
                    if holder is None:
                        continue
                    try:
                        if not self.client or not self.client.started:
                            raise RuntimeError("豆包浏览器未启动")
                        # 这里用 with_reason：未登录时把「为什么判你未登录」一并塞进异常文案，
                        # 用户看到的不是抽象的"未登录"，而是可操作的修复指引。
                        r = self.client.is_logged_in(with_reason=True)
                        if isinstance(r, tuple):
                            ok, reason = bool(r[0]), str(r[1])
                        else:
                            ok, reason = bool(r), ""
                        if not ok:
                            hint = (
                                "豆包判未登录，原因：\n" + (reason or "无更多原因") +
                                "\n\n👉 修复方法：\n"
                                "  1) 看打开的浏览器窗口右上角，如果有蓝色『登录』按钮，点它，用豆包 App 扫码登录；\n"
                                "  2) 登录成功后切回我们的软件，点顶部那粒『豆包』状态胶囊（或再次点『连接豆包』），\n"
                                "     软件会自动重检，变绿就是 OK 了；\n"
                                "  3) 如果你习惯用『本机 Edge 浏览器』并在那里已经登录过豆包，\n"
                                "     点『设置 → 浏览器来源 → 本机 Edge』→ 保存，再『连接豆包』。"
                            )
                            raise RuntimeError(hint)
                        reply = self.client.ask(instr, image, timeout)
                        holder["result"] = reply
                        self.reply_ready.emit(reply)
                        if last_login_state is not True:
                            _apply_login_state(True)
                    except Exception as e:  # noqa: BLE001
                        holder["error"] = str(e)
                        self.ask_failed.emit(str(e))
                    finally:
                        ev = self._reply_ev.get(key)
                        if ev:
                            ev.set()
                elif kind == "close":
                    if self.client:
                        try:
                            self.client.close()
                        except Exception:
                            pass
                    self._closed.set()
            except Exception as e:  # noqa: BLE001
                self._emit_log(f"豆包服务错误：{e}", "error")

    def _emit_log(self, msg: str, level: str = "info") -> None:
        self.log.emit(msg, level)


# ---------------- Agent 执行 ----------------
class AgentWorker(QThread, AgentCallbacks):
    log = Signal(str, str)
    ai = Signal(str)
    shot = Signal(bytes, int, int)
    status = Signal(str)
    done = Signal(bool, str)

    def __init__(self, config: Config, device: DeviceController,
                 doubao: DoubaoWorker, stop_event: threading.Event, parent=None):
        QThread.__init__(self, parent)
        self.config = config
        self.device = device
        self.doubao = doubao
        self.stop_event = stop_event
        self.instruction = ""

    # AgentCallbacks 实现（把回调转发到 Qt 信号，跨线程安全）
    def log_cb(self, msg: str, level: str) -> None:
        self.log.emit(msg, level)

    def ai_cb(self, msg: str) -> None:
        self.ai.emit(msg)

    def shot_cb(self, png: bytes, w: int, h: int) -> None:
        self.shot.emit(png, w, h)

    def status_cb(self, text: str) -> None:
        self.status.emit(text)

    def done_cb(self, ok: bool, reason: str) -> None:
        self.done.emit(ok, reason)

    def run(self) -> None:
        callbacks = AgentCallbacks()
        callbacks.log = self.log_cb
        callbacks.ai_message = self.ai_cb
        callbacks.screenshot = self.shot_cb
        callbacks.status = self.status_cb
        callbacks.finished = self.done_cb

        agent = PhoneAgent(self.config, self.device, self.doubao, callbacks, self.stop_event)
        agent.run(self.instruction)
