"""纯 adb 后端：只调用 adb 命令行，任何安卓版本可用，无需安装任何东西。

局限：`input text` 只支持 ASCII；中文输入请使用 uiautomator2 后端（auto）。
"""
from __future__ import annotations

import re
import shutil
import subprocess
from typing import Callable, Optional

from . import BaseBackend, DeviceError, DeviceInfo, _shell_escape

KEYCODE_MAP = {
    "HOME": 3, "BACK": 4, "MENU": 82, "APP_SWITCH": 187,
    "ENTER": 66, "POWER": 26, "VOLUME_UP": 24, "VOLUME_DOWN": 25,
    "SPACE": 62, "TAB": 61, "DEL": 67, "ESCAPE": 111,
}


class PureAdbBackend(BaseBackend):
    def __init__(self, serial: str, adb_path: str = "adb",
                 logger: Callable[[str, str], None] | None = None):
        super().__init__(serial, logger)
        self.adb = self._resolve_adb(adb_path)

    @staticmethod
    def _resolve_adb(path: str) -> str:
        if path and path != "adb":
            return path
        p = shutil.which("adb")
        if p:
            return p
        raise DeviceError(
            "未找到 adb。请安装 Android platform-tools（或设置面板里指定 adb.exe 路径）。"
        )

    def _run(self, args: list[str], timeout: int = 30) -> str:
        cmd = [self.adb, "-s", self.serial, *args]
        try:
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        except FileNotFoundError:
            raise DeviceError(f"adb 不存在：{self.adb}")
        if r.returncode != 0:
            err = (r.stderr or r.stdout or "").strip()
            raise DeviceError(f"adb 执行失败：{' '.join(cmd)}\n{err}")
        return r.stdout

    def connect(self) -> DeviceInfo:
        try:
            out = self._run(["get-state"], timeout=10).strip()
        except DeviceError as e:
            raise DeviceError(
                f"无法连接设备 {self.serial}。请确认已开启 USB 调试并授权，"
                f"或在电脑上运行 `adb devices` 检查。\n{e}"
            )
        if out != "device":
            raise DeviceError(f"设备状态异常：{out}")

        info = DeviceInfo(serial=self.serial)
        try:
            props = self._run(["shell", "getprop"])
            model = re.search(r"\[ro\.product\.model\]:\s*\[(.*?)\]", props)
            ver = re.search(r"\[ro\.build\.version\.release\]:\s*\[(.*?)\]", props)
            sdk = re.search(r"\[ro\.build\.version\.sdk\]:\s*\[(\d+)\]", props)
            info.model = model.group(1) if model else ""
            info.android_version = ver.group(1) if ver else ""
            info.sdk = int(sdk.group(1)) if sdk else 0
        except Exception:
            pass
        try:
            size = self._run(["shell", "wm", "size"]).strip()
            m = re.search(r"(\d+)x(\d+)", size)
            if m:
                info.resolution = (int(m.group(1)), int(m.group(2)))
        except Exception:
            pass
        self.log(f"已连接设备 {info.label}", "success")
        return info

    def screenshot(self) -> bytes:
        cmd = [self.adb, "-s", self.serial, "exec-out", "screencap", "-p"]
        r = subprocess.run(cmd, capture_output=True, timeout=30)
        if r.returncode != 0 or not r.stdout:
            raise DeviceError("截图失败：screencap 无输出")
        data = r.stdout
        # Windows adb 会把 \r\n 写成 \r\r\n，需要修正
        data = data.replace(b"\r\r\n", b"\r\n")
        return data

    def tap(self, x: int, y: int) -> None:
        self._run(["shell", "input", "tap", str(int(x)), str(int(y))], timeout=10)

    def swipe(self, x1: int, y1: int, x2: int, y2: int, duration_ms: int = 300) -> None:
        self._run(
            ["shell", "input", "swipe", str(int(x1)), str(int(y1)),
             str(int(x2)), str(int(y2)), str(int(duration_ms))],
            timeout=15,
        )

    def text(self, content: str) -> None:
        if any(ord(c) > 127 for c in content):
            raise DeviceError(
                "纯 adb 后端不支持中文输入（input text 仅 ASCII）。"
                "请在设置中勾选「优先使用 uiautomator2 后端」以支持中文输入。"
            )
        self._run(["shell", "input", "text", content.replace(" ", "%s")], timeout=10)

    def key(self, key: str) -> None:
        k = key.upper()
        if k in KEYCODE_MAP:
            self._run(["shell", "input", "keyevent", str(KEYCODE_MAP[k])], timeout=10)
        else:
            self._run(["shell", "input", "keyevent", k], timeout=10)

    def launch(self, package: str) -> None:
        # monkey 方式打开默认入口最通用
        self._run(
            ["shell", "monkey", "-p", package, "-c",
             "android.intent.category.LAUNCHER", "1"],
            timeout=20,
        )

    def current_app(self) -> str:
        out = self._run(["shell", "dumpsys", "window", "displays"], timeout=20)
        m = re.search(r"mCurrentFocus[^\n]*?([\w.]+/[\w.]+)", out)
        if m:
            return m.group(1).split("/")[0]
        return ""

    def disconnect(self) -> None:
        pass
