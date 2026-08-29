"""DeviceController：统一门面。自动探测设备、选择后端、执行操作并输出日志。"""
from __future__ import annotations

import re
import shutil
import subprocess
from typing import Callable, Optional

from ..config import Config
from . import BaseBackend, DeviceError, DeviceInfo
from .adb_pure import PureAdbBackend

logger_type = Callable[[str, str], None]


class DeviceController:
    def __init__(self, config: Config, logger: logger_type | None = None):
        self.config = config
        self._log = logger or (lambda msg, level="info": None)
        self.backend: BaseBackend | None = None
        self.info: DeviceInfo | None = None
        self._adb_path = str(config.get("adb_path") or "adb")

    def log(self, msg: str, level: str = "info") -> None:
        self._log(msg, level)

    # ---------- adb 基础 ----------
    @property
    def adb_path(self) -> str:
        if self._adb_path and self._adb_path != "adb":
            return self._adb_path
        return shutil.which("adb") or "adb"

    def run_adb(self, args: list[str], timeout: int = 30) -> subprocess.CompletedProcess:
        return subprocess.run(
            [self.adb_path, *args], capture_output=True, text=True, timeout=timeout
        )

    def list_devices(self) -> list[str]:
        r = self.run_adb(["devices"])
        serials = []
        for line in (r.stdout or "").splitlines()[1:]:
            parts = line.split()
            if len(parts) >= 2 and parts[1] == "device":
                serials.append(parts[0])
        return serials

    def adb_connect_wifi(self, address: str) -> None:
        if not address:
            raise DeviceError("请输入无线调试地址，格式：192.168.1.10:5555")
        r = self.run_adb(["connect", address])
        out = (r.stdout or "").strip()
        self.log(f"adb connect {address} -> {out}", "info")
        if "connected" not in out and "already" not in out:
            raise DeviceError(
                f"无线连接失败：{out}。请在手机「开发者选项」开启无线调试，"
                "并用配对码配对后重试。"
            )
        self.config.set("wifi_address", address)

    # ---------- 连接 / 断开 ----------
    def connect(self, serial: str | None = None) -> DeviceInfo:
        if not serial:
            serials = self.list_devices()
            if not serials:
                wifi = str(self.config.get("wifi_address") or "")
                if wifi:
                    serial = wifi
                else:
                    raise DeviceError(
                        "未发现设备。请用 USB 连接手机并开启「USB 调试」并授权，"
                        "或先点击「无线连接」添加地址。"
                    )
            else:
                serial = serials[0]

        prefer_u2 = bool(self.config.get("prefer_u2"))
        errs: list[str] = []

        if prefer_u2:
            from .u2 import U2Backend
            try:
                self.backend = U2Backend(serial, self._adb_path, self._log)
                self.info = self.backend.connect()
                return self.info
            except Exception as e:  # noqa: BLE001
                errs.append(str(e))

        self.backend = PureAdbBackend(serial, self._adb_path, self._log)
        try:
            self.info = self.backend.connect()
        except DeviceError:
            if prefer_u2 and errs:
                self.log("uiautomator2 与 adb 均连接失败，详见设置与日志。", "error")
            raise
        if prefer_u2 and errs:
            self.log("uiautomator2 不可用，已自动回退纯 adb 后端。", "warn")
        return self.info

    def disconnect(self) -> None:
        if self.backend:
            try:
                self.backend.disconnect()
            except Exception:
                pass
        self.backend = None
        self.info = None
        self.log("已断开设备。", "info")

    @property
    def connected(self) -> bool:
        return self.backend is not None

    # ---------- 操作转发 ----------
    def _require(self) -> BaseBackend:
        if not self.backend:
            raise DeviceError("请先连接手机。")
        return self.backend

    def screenshot(self) -> bytes:
        data = self._require().screenshot()
        self.log("截图", "info")
        return data

    def tap(self, x: int, y: int) -> None:
        self._require().tap(x, y)
        self.log(f"点击 ({x}, {y})", "action")

    def swipe(self, x1: int, y1: int, x2: int, y2: int, duration_ms: int = 300) -> None:
        self._require().swipe(x1, y1, x2, y2, duration_ms)
        self.log(f"滑动 ({x1},{y1}) -> ({x2},{y2})", "action")

    def text(self, content: str) -> None:
        self._require().text(content)
        self.log(f"输入文本：{content}", "action")

    def key(self, key: str) -> None:
        self._require().key(key)
        self.log(f"按键 {key}", "action")

    def launch(self, package: str) -> None:
        self._require().launch(package)
        self.log(f"启动应用 {package}", "action")

    def current_app(self) -> str:
        return self._require().current_app()
