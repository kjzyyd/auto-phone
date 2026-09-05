"""全局配置：持久化到用户目录的 JSON，GUI 设置面板读写。"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path


def _default_home() -> Path:
    if sys.platform == "win32":
        base = Path(os.environ.get("APPDATA", Path.home()))
        return base / "DoubaoPhoneAgent"
    return Path.home() / ".doubao_phone_agent"


def app_dir() -> Path:
    p = _default_home()
    p.mkdir(parents=True, exist_ok=True)
    return p


DEFAULTS = {
    # 设备
    "adb_path": "adb",                      # adb 可执行文件；留空自动探测 PATH/ANDROID_HOME
    "prefer_u2": True,                      # 优先 uiautomator2 后端（中文输入更强）
    "wifi_address": "",                     # 无线调试地址 ip:port
    "screen_max_width": 360,                # 截图预览面板宽度（GUI）
    # 豆包
    "doubao_url": "https://www.doubao.com/chat/",
    "user_data_dir": "",                    # 豆包浏览器会话目录（登录态持久化）
    "headless": False,                      # 豆包浏览器是否隐藏窗口
    "doubao_timeout": 180,                  # 等待 AI 回复超时（秒）
    # 浏览器来源：bundled=内置 Chromium；edge=本机 Edge（保留登录态，需调试端口）
    "browser_backend": "bundled",
    "edge_cdp_url": "http://127.0.0.1:9222",
    "edge_exe": "",                         # Edge 可执行文件路径；留空自动检测
    "edge_profile": "",                     # Edge 专用数据目录；留空用默认（登录态存于此）
    "edge_use_system_profile": False,       # True=使用你日常的 Edge 配置（你已登录的账号），False=豆包专用独立配置
    # Agent
    "max_steps": 20,                        # 单条指令最大操作轮次
    "action_interval": 0.6,                 # 每条 adb 操作间隔（秒）
    "post_screenshot_delay": 1.0,           # 截图后等待 UI 稳定（秒）
    # 通用
    "language": "zh",
}


class Config:
    def __init__(self, path: Path | None = None):
        self.path = Path(path) if path else app_dir() / "config.json"
        self._data = dict(DEFAULTS)
        self.load()

    def load(self) -> None:
        try:
            if self.path.exists():
                raw = json.loads(self.path.read_text(encoding="utf-8"))
                self._data.update(raw)
        except Exception:
            pass

    def save(self) -> None:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(
                json.dumps(self._data, ensure_ascii=False, indent=2), encoding="utf-8"
            )
        except Exception:
            pass

    def get(self, key: str):
        return self._data.get(key, DEFAULTS.get(key))

    def set(self, key: str, value) -> None:
        self._data[key] = value
        self.save()
