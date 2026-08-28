"""主窗口：设备面板 + 聊天区 + 日志 + 后台线程协调。"""
from __future__ import annotations

import threading

from PySide6.QtCore import Qt, QObject, Signal
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QLineEdit, QMainWindow, QMessageBox,
    QPlainTextEdit, QPushButton, QSizePolicy, QSplitter, QTabWidget, QVBoxLayout,
    QWidget,
)

from ..core.config import Config
from ..core.device.controller import DeviceController
from . import theme
from .dialogs import SettingsDialog
from .widgets import ChatView, LogView, ScreenshotPreview, StatusPill
from .workers import AgentWorker, DeviceWorker, DoubaoWorker


class LogBridge(QObject):
    """跨线程日志转发（信号线程安全）。"""
    log = Signal(str, str)


class MainWindow(QMainWindow):
    def __init__(self, config: Config | None = None):
        super().__init__()
        self.config = config or Config()
        self.setWindowTitle("豆包手机助手 - AI 帮你操作手机")
        self.resize(1200, 780)
        self.setMinimumSize(980, 640)
        self.setStyleSheet(theme.QSS)

        # 线程安全日志桥
        self.log_bridge = LogBridge()

        self.device = DeviceController(self.config, logger=self._safe_log)
        self.stop_event = threading.Event()

        # 豆包服务线程（常驻，独占 Playwright）
        self.doubao = DoubaoWorker(self.config)
        self.doubao.start()

        self.agent_worker: AgentWorker | None = None
        self.device_worker: DeviceWorker | None = None

        self._build_ui()
        self._connect_signals()

    # ---------------- 日志 ----------------
    def _safe_log(self, msg: str, level: str = "info") -> None:
        self.log_bridge.log.emit(msg, level)

    def _on_log(self, msg: str, level: str) -> None:
        self.log_view.append_log(msg, level)

    # ---------------- UI ----------------
    def _build_ui(self) -> None:
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(10)

        root.addWidget(self._build_header())

        body = QSplitter(Qt.Orientation.Horizontal)
        body.setChildrenCollapsible(False)
        body.addWidget(self._build_device_panel())
        body.addWidget(self._build_right_panel())
        body.setStretchFactor(0, 0)
        body.setStretchFactor(1, 1)
        body.setSizes([400, 760])
        root.addWidget(body, 1)

    def _build_header(self) -> QFrame:
        bar = QFrame()
        bar.setObjectName("HeaderBar")
        bar.setFixedHeight(60)
        lay = QHBoxLayout(bar)
        lay.setContentsMargins(18, 8, 14, 8)
        lay.setSpacing(12)

        logo = QLabel("豆")
        logo.setObjectName("LogoLabel")
        logo.setFixedSize(38, 38)
        logo.setAlignment(Qt.AlignmentFlag.AlignCenter)
        logo.setStyleSheet(
            "background:qlineargradient(x1:0,y1:0,x2:1,y2:1, stop:0 %s, stop:1 %s);"
            "border-radius:10px; color:white; font-size:20px; font-weight:800;"
            % (theme.ACCENT, theme.ACCENT2)
        )
        lay.addWidget(logo)

        title_box = QVBoxLayout()
        title_box.setSpacing(0)
        t = QLabel("豆包手机助手")
        t.setObjectName("AppTitle")
        sub = QLabel("网页版豆包 AI + adb 自动化操作安卓手机")
        sub.setObjectName("AppSubtitle")
        title_box.addWidget(t)
        title_box.addWidget(sub)
        lay.addLayout(title_box)
        lay.addStretch(1)

        self.device_pill = StatusPill("手机未连接", theme.ERROR)
        self.doubao_pill = StatusPill("豆包未连接", theme.ERROR)
        lay.addWidget(self.device_pill)
        lay.addWidget(self.doubao_pill)

        self.btn_connect = QPushButton("连接手机")
        self.btn_connect.setProperty("primary", True)
        self.btn_connect.setFixedHeight(34)
        self.btn_doubao = QPushButton("连接豆包")
        self.btn_doubao.setFixedHeight(34)
        self.btn_settings = QPushButton("设置")
        self.btn_settings.setFixedHeight(34)
        lay.addWidget(self.btn_connect)
        lay.addWidget(self.btn_doubao)
        lay.addWidget(self.btn_settings)
        return bar

    def _build_device_panel(self) -> QFrame:
        panel = QFrame()
        panel.setObjectName("DevicePanel")
        lay = QVBoxLayout(panel)
        lay.setContentsMargins(14, 14, 14, 14)
        lay.setSpacing(10)

        sec = QLabel("手机设备")
        sec.setProperty("sectionTitle", True)
        lay.addWidget(sec)

        info_card = QFrame()
        info_card.setProperty("card", True)
        ic = QVBoxLayout(info_card)
        ic.setContentsMargins(12, 10, 12, 10)
        ic.setSpacing(4)
        self.lbl_model = QLabel("未连接")
        self.lbl_model.setStyleSheet("font-size:14px; font-weight:700;")
        self.lbl_info = QLabel("请用 USB 连接并开启调试，或输入无线地址")
        self.lbl_info.setStyleSheet(f"color:{theme.MUTED}; font-size:12px;")
        self.lbl_res = QLabel("")
        self.lbl_res.setStyleSheet(f"color:{theme.MUTED}; font-size:12px;")
        ic.addWidget(self.lbl_model)
        ic.addWidget(self.lbl_info)
        ic.addWidget(self.lbl_res)
        lay.addWidget(info_card)

        # 快捷操作
        quick = QHBoxLayout()
        quick.setSpacing(6)
        self.quick_btns = []
        for text, key in [("返回", "BACK"), ("主页", "HOME"), ("多任务", "APP_SWITCH")]:
            b = QPushButton(text)
            b.setProperty("small", True)
            b.setEnabled(False)
            b.clicked.connect(lambda _, k=key: self.device.key(k))
            self.quick_btns.append(b)
            quick.addWidget(b)
        self.btn_refresh_shot = QPushButton("刷新截图")
        self.btn_refresh_shot.setProperty("small", True)
        self.btn_refresh_shot.setEnabled(False)
        self.btn_refresh_shot.clicked.connect(self._manual_screenshot)
        self.quick_btns.append(self.btn_refresh_shot)
        quick.addWidget(self.btn_refresh_shot)
        lay.addLayout(quick)

        # 屏幕预览
        self.preview = ScreenshotPreview()
        lay.addWidget(self.preview, 1)
        hint = QLabel("提示：单击预览画面 = 在手机上点击该位置（手动干预）")
        hint.setStyleSheet(f"color:{theme.MUTED}; font-size:11px;")
        hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(hint)

        # 无线连接
        wifi_row = QHBoxLayout()
        self.wifi_input = QLineEdit(str(self.config.get("wifi_address") or ""))
        self.wifi_input.setPlaceholderText("无线调试地址 ip:port")
        self.btn_wifi = QPushButton("无线连接")
        self.btn_wifi.setProperty("small", True)
        self.btn_wifi.clicked.connect(self._wifi_connect)
        wifi_row.addWidget(self.wifi_input, 1)
        wifi_row.addWidget(self.btn_wifi)
        lay.addLayout(wifi_row)
        return panel

    def _build_right_panel(self) -> QFrame:
        panel = QFrame()
        panel.setObjectName("RightPanel")
        lay = QVBoxLayout(panel)
        lay.setContentsMargins(2, 2, 2, 2)

        tabs = QTabWidget()
        # ---- 对话 ----
        chat_tab = QWidget()
        ct = QVBoxLayout(chat_tab)
        ct.setContentsMargins(4, 4, 4, 4)
        ct.setSpacing(8)
        self.chat_view = ChatView()
        ct.addWidget(self.chat_view, 1)

        input_bar = QFrame()
        input_bar.setProperty("card", True)
        ib = QVBoxLayout(input_bar)
        ib.setContentsMargins(10, 10, 10, 10)
        ib.setSpacing(8)
        self.input_edit = QPlainTextEdit()
        self.input_edit.setPlaceholderText(
            "输入你想让豆包在手机上做的事，例如：打开微信，给张三发消息「晚上一起吃饭」，然后回到桌面"
        )
        self.input_edit.setMaximumHeight(90)
        self.input_edit.setMinimumHeight(64)
        ib.addWidget(self.input_edit)
        btn_row = QHBoxLayout()
        self.btn_clear = QPushButton("清空对话")
        self.btn_clear.setProperty("small", True)
        self.btn_stop = QPushButton("停止")
        self.btn_stop.setProperty("small", True)
        self.btn_stop.setProperty("danger", True)
        self.btn_stop.setEnabled(False)
        self.btn_send = QPushButton("发送指令")
        self.btn_send.setProperty("primary", True)
        self.btn_send.setFixedHeight(34)
        btn_row.addWidget(self.btn_clear)
        btn_row.addStretch(1)
        btn_row.addWidget(self.btn_stop)
        btn_row.addWidget(self.btn_send)
        ib.addLayout(btn_row)
        ct.addWidget(input_bar)
        tabs.addTab(chat_tab, "对话")

        # ---- 日志 ----
        log_tab = QWidget()
        lt = QVBoxLayout(log_tab)
        lt.setContentsMargins(4, 4, 4, 4)
        lt.setSpacing(6)
        self.log_view = LogView()
        lt.addWidget(self.log_view, 1)
        lr = QHBoxLayout()
        lr.addStretch(1)
        btn_clear_log = QPushButton("清空日志")
        btn_clear_log.setProperty("small", True)
        btn_clear_log.clicked.connect(self.log_view.clear_log)
        lr.addWidget(btn_clear_log)
        lt.addLayout(lr)
        tabs.addTab(log_tab, "操作日志")

        lay.addWidget(tabs)
        return panel

    # ---------------- 信号 ----------------
    def _connect_signals(self) -> None:
        self.log_bridge.log.connect(self._on_log)
        self.btn_connect.clicked.connect(self._connect_device)
        self.btn_doubao.clicked.connect(self._connect_doubao)
        self.btn_settings.clicked.connect(self._open_settings)
        self.btn_send.clicked.connect(self._send)
        self.btn_clear.clicked.connect(self._clear_chat)
        self.btn_stop.clicked.connect(self._stop)
        self.preview.tapped.connect(self._preview_tap)

        # 快捷键：Ctrl+Enter 发送
        sc = QShortcut(QKeySequence("Ctrl+Return"), self)
        sc.activated.connect(self._send)

        # 豆包线程信号
        self.doubao.started.connect(lambda: (
            self.doubao_pill.set_state("浏览器已打开，等待登录", theme.WARN),
            self._safe_log("豆包浏览器已打开，请在窗口中扫码/登录。", "info"),
        ))
        self.doubao.login_changed.connect(self._on_doubao_login)
        self.doubao.ask_failed.connect(
            lambda msg: (self._safe_log(f"豆包：{msg}", "error"),
                         self.chat_view.add_system(f"豆包出错：{msg}", theme.ERROR))
        )
        self.doubao.log.connect(self._safe_log)
        self.doubao.closed.connect(
            lambda: self.doubao_pill.set_state("豆包未连接", theme.ERROR)
        )

    def _on_doubao_login(self, ok: bool) -> None:
        if ok:
            self.doubao_pill.set_state("豆包已登录", theme.SUCCESS)
            self._safe_log("豆包登录成功，可以开始使用。", "success")
        else:
            self.doubao_pill.set_state("等待登录", theme.WARN)

    # ---------------- 设备动作 ----------------
    def _connect_device(self) -> None:
        if self.device_worker and self.device_worker.isRunning():
            return
        self.btn_connect.setEnabled(False)
        self.btn_connect.setText("连接中…")
        self.device_pill.set_state("连接中…", theme.WARN)
        self._safe_log("正在连接手机…", "info")
        self.device_worker = DeviceWorker(self.device, None)
        self.device_worker.connected.connect(self._on_device_connected)
        self.device_worker.failed.connect(self._on_device_failed)
        self.device_worker.finished.connect(self._on_device_worker_done)
        self.device_worker.start()

    def _on_device_connected(self, info) -> None:
        self.device_pill.set_state(f"已连接 {info.model or info.serial}", theme.SUCCESS)
        self.lbl_model.setText(info.model or info.serial)
        parts = []
        if info.android_version:
            parts.append(f"Android {info.android_version}")
        if info.resolution != (0, 0):
            parts.append(f"{info.resolution[0]}x{info.resolution[1]}")
        self.lbl_info.setText(f"序列号：{info.serial}")
        self.lbl_res.setText(" / ".join(parts))
        for b in self.quick_btns:
            b.setEnabled(True)
        self._safe_log(f"设备连接成功：{info.label}", "success")
        self._manual_screenshot()

    def _on_device_failed(self, msg: str) -> None:
        self._safe_log(f"连接失败：{msg}", "error")
        self.lbl_model.setText("连接失败")

    def _on_device_worker_done(self) -> None:
        self.btn_connect.setEnabled(True)
        self.btn_connect.setText("连接手机")

    def _wifi_connect(self) -> None:
        try:
            self.device.adb_connect_wifi(self.wifi_input.text().strip())
            self._connect_device()
        except Exception as e:  # noqa: BLE001
            self._safe_log(f"无线连接失败：{e}", "error")

    def _manual_screenshot(self) -> None:
        try:
            png = self.device.screenshot()
            w, h = (self.device.info.resolution if self.device.info else (0, 0))
            self.preview.set_screenshot(png, w, h)
        except Exception as e:  # noqa: BLE001
            self._safe_log(f"截图失败：{e}", "error")

    def _preview_tap(self, x: int, y: int) -> None:
        if not self.device.connected:
            self._safe_log("手机未连接，无法点击。", "warn")
            return
        try:
            self.device.tap(x, y)
            self._safe_log(f"手动点击 ({x}, {y})", "action")
        except Exception as e:  # noqa: BLE001
            self._safe_log(f"点击失败：{e}", "error")

    # ---------------- 豆包动作 ----------------
    def _connect_doubao(self) -> None:
        self.btn_doubao.setEnabled(False)
        self.doubao.request_start()

    # ---------------- 发送 / 停止 ----------------
    def _send(self) -> None:
        if self.agent_worker and self.agent_worker.isRunning():
            self._safe_log("任务正在执行中，请先停止。", "warn")
            return
        text = self.input_edit.toPlainText().strip()
        if not text:
            return
        if not self.device.connected:
            self._safe_log("请先连接手机。", "warn")
            return
        self.chat_view.add_user(text)
        self.input_edit.clear()
        self.stop_event.clear()
        self.btn_stop.setEnabled(True)
        self.btn_send.setEnabled(False)

        self.agent_worker = AgentWorker(
            self.config, self.device, self.doubao, self.stop_event
        )
        self.agent_worker.instruction = text
        self.agent_worker.log.connect(self._safe_log)
        self.agent_worker.ai.connect(self.chat_view.add_ai)
        self.agent_worker.shot.connect(self.preview.set_screenshot)
        self.agent_worker.status.connect(self._on_agent_status)
        self.agent_worker.done.connect(self._on_agent_done)
        self.agent_worker.start()

    def _stop(self) -> None:
        self.stop_event.set()
        self._safe_log("正在停止…", "warn")

    def _on_agent_status(self, text: str) -> None:
        self.device_pill.set_state(text, theme.WARN)

    def _on_agent_done(self, ok: bool, reason: str) -> None:
        self.btn_stop.setEnabled(False)
        self.btn_send.setEnabled(True)
        if ok:
            self.chat_view.add_system(f"任务完成：{reason}", theme.SUCCESS)
        else:
            self.chat_view.add_system(f"任务结束：{reason}", theme.WARN)
        if self.device.info:
            self.device_pill.set_state(
                f"已连接 {self.device.info.model or self.device.info.serial}",
                theme.SUCCESS,
            )

    def _clear_chat(self) -> None:
        self.chat_view.clear_chat()

    # ---------------- 设置 ----------------
    def _open_settings(self) -> None:
        dlg = SettingsDialog(self.config, self)
        if dlg.exec():
            self.device._adb_path = str(self.config.get("adb_path"))
            self._safe_log("设置已保存。", "success")

    def closeEvent(self, e) -> None:  # noqa: N802
        self.stop_event.set()
        try:
            self.doubao.request_close()
        except Exception:
            pass
        self.doubao.wait(3000)
        super().closeEvent(e)
