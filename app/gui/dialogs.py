"""设置对话框。"""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QDialogButtonBox, QDoubleSpinBox, QFileDialog, QFormLayout,
    QGroupBox, QHBoxLayout, QLineEdit, QPushButton, QSpinBox, QVBoxLayout, QWidget,
)

from ..core.config import Config
from . import theme


class SettingsDialog(QDialog):
    def __init__(self, config: Config, parent=None):
        super().__init__(parent)
        self.config = config
        self.setWindowTitle("设置")
        self.setMinimumWidth(460)
        self._build()

    def _build(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(18, 18, 18, 18)
        root.setSpacing(10)

        # ---- 设备 ----
        dev = QGroupBox("手机设备（adb）")
        fl = QFormLayout(dev)
        self.adb_path = QLineEdit(str(self.config.get("adb_path")))
        self.adb_path.setPlaceholderText("留空自动探测 PATH / ANDROID_HOME")
        fl.addRow("adb 路径：", self.adb_path)
        self.prefer_u2 = QCheckBox("优先使用 uiautomator2 后端（支持中文输入，首次自动部署）")
        self.prefer_u2.setChecked(bool(self.config.get("prefer_u2")))
        fl.addRow("", self.prefer_u2)
        self.wifi = QLineEdit(str(self.config.get("wifi_address")))
        self.wifi.setPlaceholderText("例如 192.168.1.10:5555")
        fl.addRow("无线调试地址：", self.wifi)
        root.addWidget(dev)

        # ---- 豆包 ----
        db = QGroupBox("豆包网页")
        fl2 = QFormLayout(db)
        self.browser_backend = QComboBox()
        self.browser_backend.addItem("内置 Chromium（随软件打包，无需额外安装）", "bundled")
        self.browser_backend.addItem("本机 Edge 浏览器（保留登录态，推荐）", "edge")
        idx = self.browser_backend.findData(str(self.config.get("browser_backend")))
        self.browser_backend.setCurrentIndex(max(idx, 0))
        self.browser_backend.currentIndexChanged.connect(self._toggle_edge_fields)
        fl2.addRow("浏览器来源：", self.browser_backend)

        row = QWidget()
        h = QHBoxLayout(row)
        h.setContentsMargins(0, 0, 0, 0)
        self.profile = QLineEdit(str(self.config.get("user_data_dir")))
        self.profile.setPlaceholderText("留空使用默认目录（登录态会自动保存）")
        btn_browse = QPushButton("选择")
        btn_browse.setProperty("small", True)
        btn_browse.clicked.connect(self._browse_profile)
        h.addWidget(self.profile, 1)
        h.addWidget(btn_browse)
        fl2.addRow("浏览器数据目录：", row)

        self.edge_exe = QLineEdit(str(self.config.get("edge_exe")))
        self.edge_exe.setPlaceholderText("留空自动检测（C:\\Program Files\\Microsoft\\Edge 等）")
        fl2.addRow("Edge 可执行文件：", self.edge_exe)

        self.edge_profile_mode = QComboBox()
        self.edge_profile_mode.addItem("豆包专用（独立配置，不影响日常 Edge）", "dedicated")
        self.edge_profile_mode.addItem("我日常的 Edge 配置（已有登录账号，推荐）", "system")
        mode = "system" if bool(self.config.get("edge_use_system_profile")) else "dedicated"
        idx = self.edge_profile_mode.findData(mode)
        self.edge_profile_mode.setCurrentIndex(max(idx, 0))
        self.edge_profile_mode.currentIndexChanged.connect(self._toggle_edge_fields)
        fl2.addRow("Edge 配置来源：", self.edge_profile_mode)
        self.edge_profile_hint = QLabel(
            "选择『我日常的 Edge 配置』可直接复用你已登录的豆包账号；\n"
            "若连接失败，请先彻底退出 Edge（含托盘图标）再点「连接豆包」。"
        )
        self.edge_profile_hint.setWordWrap(True)
        self.edge_profile_hint.setStyleSheet("color: " + theme.MUTED + "; font-size: 11px;")
        fl2.addRow("", self.edge_profile_hint)

        self.edge_cdp = QLineEdit(str(self.config.get("edge_cdp_url")))
        self.edge_cdp.setPlaceholderText("例如 http://127.0.0.1:9222")
        fl2.addRow("Edge 调试端口：", self.edge_cdp)

        self.headless = QCheckBox("隐藏豆包浏览器窗口（后台运行，建议保持关闭以便扫码登录）")
        self.headless.setChecked(bool(self.config.get("headless")))
        fl2.addRow("", self.headless)
        root.addWidget(db)
        self._toggle_edge_fields()

        # ---- 任务 ----
        tk = QGroupBox("自动任务")
        fl3 = QFormLayout(tk)
        self.max_steps = QSpinBox()
        self.max_steps.setRange(3, 100)
        self.max_steps.setValue(int(self.config.get("max_steps")))
        fl3.addRow("最大操作轮数：", self.max_steps)
        self.action_interval = QDoubleSpinBox()
        self.action_interval.setRange(0.1, 10.0)
        self.action_interval.setSingleStep(0.1)
        self.action_interval.setValue(float(self.config.get("action_interval")))
        fl3.addRow("每条操作间隔（秒）：", self.action_interval)
        self.timeout = QSpinBox()
        self.timeout.setRange(30, 600)
        self.timeout.setValue(int(self.config.get("doubao_timeout")))
        fl3.addRow("等待 AI 回复超时（秒）：", self.timeout)
        root.addWidget(tk)

        # ---- 按钮 ----
        btns = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        btns.accepted.connect(self._save)
        btns.rejected.connect(self.reject)
        root.addWidget(btns)

        self.setStyleSheet(theme.QSS)

    def _browse_profile(self) -> None:
        d = QFileDialog.getExistingDirectory(self, "选择浏览器数据目录")
        if d:
            self.profile.setText(d)

    def _toggle_edge_fields(self) -> None:
        is_edge = self.browser_backend.currentData() == "edge"
        # 仅 Edge 模式才需要 Edge 专用字段
        for w in (self.edge_exe, self.edge_cdp, self.edge_profile_mode, self.edge_profile_hint):
            w.setEnabled(is_edge)

    def _save(self) -> None:
        self.config.set("adb_path", self.adb_path.text().strip())
        self.config.set("prefer_u2", self.prefer_u2.isChecked())
        self.config.set("wifi_address", self.wifi.text().strip())
        self.config.set("browser_backend", self.browser_backend.currentData())
        self.config.set("user_data_dir", self.profile.text().strip())
        self.config.set("edge_exe", self.edge_exe.text().strip())
        self.config.set("edge_cdp_url", self.edge_cdp.text().strip() or "http://127.0.0.1:9222")
        self.config.set("edge_use_system_profile", self.edge_profile_mode.currentData() == "system")
        self.config.set("headless", self.headless.isChecked())
        self.config.set("max_steps", self.max_steps.value())
        self.config.set("action_interval", self.action_interval.value())
        self.config.set("doubao_timeout", self.timeout.value())
        self.accept()
