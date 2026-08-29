"""设备控制层：抽象后端 + 纯 adb 后端 + uiautomator2 后端 + 统一门面。

所有后端都只依赖 adb 通道（USB 或 无线调试），无需在手机上安装任何用户可见 App。
"""
from __future__ import annotations

import dataclasses
import subprocess
import sys
from typing import Callable, Optional


class DeviceError(RuntimeError):
    """设备操作异常（含对用户友好的中文提示）。"""


@dataclasses.dataclass
class DeviceInfo:
    serial: str
    model: str = ""
    android_version: str = ""
    sdk: int = 0
    resolution: tuple[int, int] = (0, 0)  # (宽, 高)

    @property
    def label(self) -> str:
        parts = [self.serial]
        if self.model:
            parts.append(self.model)
        if self.android_version:
            parts.append(f"Android {self.android_version}")
        return " / ".join(parts)


class BaseBackend:
    """后端统一接口。screenshot 返回 PNG bytes，坐标为设备物理像素。"""

    def __init__(self, serial: str, logger: Callable[[str, str], None] | None = None):
        self.serial = serial
        self._log = logger or (lambda msg, level="info": None)

    def log(self, msg: str, level: str = "info") -> None:
        self._log(msg, level)

    def connect(self) -> DeviceInfo:  # pragma: no cover - 子类实现
        raise NotImplementedError

    def screenshot(self) -> bytes:  # pragma: no cover
        raise NotImplementedError

    def tap(self, x: int, y: int) -> None:  # pragma: no cover
        raise NotImplementedError

    def swipe(self, x1: int, y1: int, x2: int, y2: int, duration_ms: int = 300) -> None:  # pragma: no cover
        raise NotImplementedError

    def text(self, content: str) -> None:  # pragma: no cover
        raise NotImplementedError

    def key(self, key: str) -> None:  # pragma: no cover
        raise NotImplementedError

    def launch(self, package: str) -> None:  # pragma: no cover
        raise NotImplementedError

    def current_app(self) -> str:  # pragma: no cover
        raise NotImplementedError

    def disconnect(self) -> None:  # pragma: no cover
        pass


def _shell_escape(s: str) -> str:
    """adb shell 参数转义（单引号包裹，内部单引号转义）。"""
    return "'" + s.replace("'", "'\\''") + "'"
