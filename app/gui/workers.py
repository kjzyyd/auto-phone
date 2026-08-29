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
        waiting_login = False
        while not self._closed.is_set():
            # 登录轮询（非阻塞，保持队列可用）
            if waiting_login and self.client is not None:
                try:
                    if self.client.is_logged_in():
                        waiting_login = False
                        self.login_changed.emit(True)
                except Exception:
                    pass

            try:
                cmd = self._q.get(timeout=0.3)
            except queue.Empty:
                continue
            kind = cmd[0]
            try:
                if kind == "start":
                    self.client = DoubaoClient(self.config, self._emit_log)
                    self.client.ensure_browser()
                    self.client.start()
                    self.started.emit()
                    waiting_login = True
                elif kind == "check_login":
                    ok = bool(self.client and self.client.is_logged_in())
                    self.login_changed.emit(ok)
                elif kind == "ask":
                    _, key, instr, image, timeout = cmd
                    holder = self._reply_box.get(key)
                    if holder is None:
                        continue
                    try:
                        if not self.client or not self.client.started:
                            raise RuntimeError("豆包浏览器未启动")
                        if not self.client.is_logged_in():
                            raise RuntimeError(
                                "豆包未登录。请在打开的浏览器中扫码/登录后重试。"
                            )
                        reply = self.client.ask(instr, image, timeout)
                        holder["result"] = reply
                        self.reply_ready.emit(reply)
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
