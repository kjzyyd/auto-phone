"""PhoneAgent：人机协作的核心循环。
流程：截图 -> 发给豆包(附指令) -> 解析动作 -> adb 执行 -> 再截图 -> ... -> DONE。
"""
from __future__ import annotations

import threading
import time
from typing import Callable, Optional

from .config import Config
from . import parser
from . import prompt as prompt_mod
from .device.controller import DeviceController

# 通知接口：GUI 层实现
class AgentCallbacks:
    def log(self, msg: str, level: str = "info") -> None: ...
    def ai_message(self, msg: str) -> None: ...
    def screenshot(self, png: bytes, width: int, height: int) -> None: ...
    def status(self, text: str) -> None: ...
    def finished(self, ok: bool, reason: str) -> None: ...


class PhoneAgent:
    def __init__(
        self,
        config: Config,
        device: DeviceController,
        doubao: object,          # DoubaoClient（鸭子类型：ask(instruction, image) -> str）
        cb: AgentCallbacks,
        stop_event: threading.Event,
    ):
        self.config = config
        self.device = device
        self.doubao = doubao
        self.cb = cb
        self.stop = stop_event

    def _sleep(self, seconds: float) -> bool:
        """可中断 sleep；被停止返回 False。"""
        end = time.time() + seconds
        while time.time() < end:
            if self.stop.is_set():
                return False
            time.sleep(0.1)
        return not self.stop.is_set()

    def run(self, instruction: str) -> None:
        if not self.device.connected:
            self.cb.finished(False, "手机未连接")
            return
        try:
            self._run(instruction)
        except Exception as e:  # noqa: BLE001
            self.cb.log(f"任务异常终止：{e}", "error")
            self.cb.finished(False, str(e))

    def _run(self, instruction: str) -> None:
        max_steps = int(self.config.get("max_steps"))
        interval = float(self.config.get("action_interval"))
        shot_delay = float(self.config.get("post_screenshot_delay"))
        timeout = int(self.config.get("doubao_timeout"))

        self.cb.status("任务进行中")
        self.cb.log(f"开始执行指令：{instruction}", "info")

        step = 0
        last_reply = ""
        done_reason = ""
        while step < max_steps:
            if self.stop.is_set():
                self.cb.finished(False, "用户已停止")
                return
            step += 1
            self.cb.status(f"任务进行中（第 {step}/{max_steps} 轮）")

            # 1. 截图
            png = self.device.screenshot()
            w, h = (self.device.info.resolution if self.device.info else (0, 0))
            self.cb.screenshot(png, w, h)
            if not self._sleep(shot_delay):
                self.cb.finished(False, "用户已停止")
                return

            # 2. 问豆包
            self.cb.status(f"正在询问豆包…（第 {step}/{max_steps} 轮）")
            if step == 1:
                question = prompt_mod.first_turn(instruction, self._screen_desc())
            else:
                question = prompt_mod.followup_turn(last_reply)
            reply = self.doubao.ask(question, image=png, timeout=timeout)
            last_reply = reply
            self.cb.ai_message(reply)
            if self.stop.is_set():
                self.cb.finished(False, "用户已停止")
                return

            # 3. 解析动作
            actions = parser.parse_actions(reply)
            if not actions:
                self.cb.log("豆包给出的是纯文字回答，未包含操作指令，任务结束。", "info")
                self.cb.finished(True, "豆包已文字回答，无需继续操作")
                return

            # 4. 执行动作
            terminal = False
            for act in actions:
                if self.stop.is_set():
                    self.cb.finished(False, "用户已停止")
                    return
                self.cb.log(f"[动作] {act.describe()}", "action")
                self._execute(act)
                if act.verb == "done":
                    done_reason = " ".join(act.args)
                    terminal = True
                    break
                if not self._sleep(interval):
                    self.cb.finished(False, "用户已停止")
                    return

            if terminal:
                self.cb.log(f"任务完成：{done_reason}", "success")
                self.cb.finished(True, done_reason or "任务完成")
                return

        self.cb.log(f"达到最大轮数 {max_steps}，任务结束。", "warn")
        self.cb.finished(False, f"达到最大操作轮数（{max_steps}），可能未完成，可在设置中调大")

    def _screen_desc(self) -> str:
        if self.device.info and self.device.info.resolution != (0, 0):
            w, h = self.device.info.resolution
            return f"{w}x{h}px"
        return "尺寸未知"

    def _execute(self, act: parser.Action) -> None:
        verb, args = act.verb, act.args
        if verb == "tap":
            self.device.tap(int(float(args[0])), int(float(args[1])))
        elif verb == "swipe":
            nums = [int(float(x)) for x in args[:4]]
            dur = int(float(args[4])) if len(args) > 4 else 300
            self.device.swipe(*nums, dur)
        elif verb == "text":
            self.device.text(args[0] if args else "")
        elif verb == "key":
            self.device.key(args[0] if args else "HOME")
        elif verb == "launch":
            self.device.launch(args[0] if args else "")
        elif verb == "wait":
            self._sleep(max(0.0, float(args[0]) / 1000.0 if args else 0.5))
        elif verb == "shot":
            pass  # 下一轮循环自然会截图
