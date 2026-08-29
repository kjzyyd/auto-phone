"""uiautomator2 后端：功能最全（中文输入、元素定位），首次使用会通过 adb 自动部署
atx-agent / uiautomator2 server 到手机（后台自动化服务，无用户可见界面）。
"""
from __future__ import annotations

import io
from typing import Callable, Optional

from . import BaseBackend, DeviceError, DeviceInfo

_KEYMAP = {
    "HOME": "home", "BACK": "back", "MENU": "menu",
    "APP_SWITCH": "recent", "ENTER": "enter", "POWER": "power",
}


class U2Backend(BaseBackend):
    def __init__(self, serial: str, adb_path: str = "adb",
                 logger: Callable[[str, str], None] | None = None):
        super().__init__(serial, logger)
        try:
            import uiautomator2 as u2  # 延迟导入，避免无手机时拖慢启动
        except ImportError:
            raise DeviceError("缺少 uiautomator2 依赖，请执行：pip install uiautomator2")
        self._u2 = u2
        self._adb_path = adb_path
        self._dev = None
        self._fastinput_ready = False

    def connect(self) -> DeviceInfo:
        try:
            self._dev = self._u2.connect(self.serial)
            info = self._dev.device_info
        except Exception as e:
            raise DeviceError(
                f"uiautomator2 连接失败（{e}）。将回退到纯 adb 后端。"
            )

        d = self._dev
        resolution = None
        try:
            w, h = d.window_size()
            resolution = (int(w), int(h))
        except Exception:
            resolution = (0, 0)

        info_obj = DeviceInfo(
            serial=self.serial,
            model=(info.get("model") or "").replace(" ", ""),
            android_version=str(info.get("version") or info.get("androidVersion") or ""),
            sdk=int(info.get("sdk") or info.get("android") or 0 or 0) if isinstance(
                info.get("sdk") or info.get("android"), int) else 0,
            resolution=resolution,
        )
        try:
            info_obj.sdk = int(info.get("sdk") or 0)
        except Exception:
            pass
        self.log(f"已连接设备 {info_obj.label}（uiautomator2）", "success")
        return info_obj

    def screenshot(self) -> bytes:
        img = self._dev.screenshot()
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return buf.getvalue()

    def tap(self, x: int, y: int) -> None:
        self._dev.click(int(x), int(y))

    def swipe(self, x1: int, y1: int, x2: int, y2: int, duration_ms: int = 300) -> None:
        self._dev.swipe(int(x1), int(y1), int(x2), int(y2), duration=duration_ms / 1000.0)

    def text(self, content: str) -> None:
        if not self._fastinput_ready:
            try:
                self._dev.set_fastinput_ime(True)  # 自动安装并启用 ADBKeyboard（支持中文）
                self._fastinput_ready = True
            except Exception:
                pass
        self._dev.send_keys(content)

    def key(self, key: str) -> None:
        k = key.upper()
        mapped = _KEYMAP.get(k, k.lower())
        try:
            self._dev.press(mapped)
        except Exception:
            self._dev.keyevent(mapped)

    def launch(self, package: str) -> None:
        self._dev.app_start(package)

    def current_app(self) -> str:
        try:
            return (self._dev.app_current() or {}).get("package", "")
        except Exception:
            return ""

    def disconnect(self) -> None:
        try:
            if self._fastinput_ready:
                self._dev.set_fastinput_ime(False)
        except Exception:
            pass
