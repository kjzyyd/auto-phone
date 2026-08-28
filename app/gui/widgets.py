"""通用控件：状态胶囊 / 聊天视图 / 截图预览 / 日志视图。"""
from __future__ import annotations

import html
import time

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QPlainTextEdit, QTextBrowser, QVBoxLayout, QWidget,
)

from . import theme


# ---------------- 状态胶囊 ----------------
class StatusPill(QFrame):
    def __init__(self, text: str = "未连接", color: str = theme.MUTED, parent=None):
        super().__init__(parent)
        self.setProperty("pill", True)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(12, 4, 12, 4)
        lay.setSpacing(6)
        self.dot = QLabel("●")
        self.dot.setProperty("pillDot", True)
        self.label = QLabel(text)
        self.label.setProperty("pillText", True)
        lay.addWidget(self.dot)
        lay.addWidget(self.label)
        self.set_color(color)

    def set_state(self, text: str, color: str) -> None:
        self.label.setText(text)
        self.set_color(color)

    def set_color(self, color: str) -> None:
        self.dot.setStyleSheet(f"color: {color};")


# ---------------- 聊天视图 ----------------
class ChatView(QTextBrowser):
    """支持富文本聊天气泡的只读视图。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("ChatView")
        self.setOpenExternalLinks(True)
        self.setHtml(self._page())
        self._parts: list[str] = []
        self._welcome()

    @staticmethod
    def _page() -> str:
        return f"""
        <html><body style="background:{theme.CARD}; color:{theme.TEXT};
        font-family:{theme.FONT_STACK};">
        </body></html>"""

    def _welcome(self) -> None:
        self.add_system(
            "欢迎使用豆包手机助手\n"
            "1. 连接手机（USB 调试 / 无线调试）\n"
            "2. 连接豆包，在打开的浏览器中扫码登录\n"
            "3. 输入指令，例如：打开微信，给张三发消息「晚上一起吃饭」"
        )

    def _esc(self, s: str) -> str:
        return html.escape(s).replace("\n", "<br>")

    def add_user(self, text: str) -> None:
        self._parts.append(
            f'<div style="display:flex; justify-content:flex-end; margin:6px 2px;">'
            f'<div style="max-width:75%; background:linear-gradient(135deg,'
            f'{theme.ACCENT},{theme.ACCENT2}); color:white; border-radius:14px 14px 2px 14px;'
            f'padding:9px 13px;">{self._esc(text)}</div></div>'
        )
        self._render()

    def add_ai(self, text: str) -> None:
        self._parts.append(
            f'<div style="display:flex; justify-content:flex-start; margin:6px 2px;">'
            f'<div style="max-width:85%; background:#242C3D; color:{theme.TEXT};'
            f'border:1px solid {theme.BORDER}; border-radius:14px 14px 14px 2px;'
            f'padding:9px 13px; white-space:pre-wrap;">{self._esc(text)}</div></div>'
        )
        self._render()

    def add_system(self, text: str, color: str = theme.MUTED) -> None:
        self._parts.append(
            f'<div style="text-align:center; color:{color}; font-size:11px; '
            f'margin:4px 2px;">{self._esc(text)}</div>'
        )
        self._render()

    def _render(self) -> None:
        self.setHtml(self._page().replace("</body></html>",
                                          "".join(self._parts) + "</body></html>"))
        sb = self.verticalScrollBar()
        sb.setValue(sb.maximum())

    def clear_chat(self) -> None:
        self._parts = []
        self._welcome()


# ---------------- 截图预览 ----------------
class ScreenshotPreview(QLabel):
    """手机屏幕预览。点击图片 = 点击手机对应坐标（手动干预）。"""

    tapped = Signal(int, int)  # 设备像素坐标

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setMinimumSize(200, 300)
        self.setStyleSheet(
            f"background:{theme.BG}; border:1px solid {theme.BORDER}; border-radius:10px;"
        )
        self._pixmap: QPixmap | None = None
        self._scale = 1.0
        self._last_pos: tuple[int, int] | None = None
        self.setCursor(Qt.CursorShape.CrossCursor)
        self.setText("屏幕预览\n（连接手机后自动刷新）")
        self.setToolTip("单击 = 在手机上点击该位置")

    def set_screenshot(self, png: bytes, w: int, h: int) -> None:
        pm = QPixmap()
        if not pm.loadFromData(png, "PNG"):
            return
        self._pixmap = pm
        self._last_pos = None
        self._update_scale()
        self.update()

    def _update_scale(self) -> None:
        if not self._pixmap:
            return
        avail_w = max(self.width() - 8, 1)
        avail_h = max(self.height() - 8, 1)
        self._scale = min(avail_w / self._pixmap.width(), avail_h / self._pixmap.height())
        self._scale = min(self._scale, 1.0)

    def resizeEvent(self, e) -> None:  # noqa: N802
        super().resizeEvent(e)
        self._update_scale()

    def paintEvent(self, e) -> None:  # noqa: N802
        super().paintEvent(e)
        if not self._pixmap or self._last_pos is None:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        cx, cy = self._last_pos
        pen = QPen(QColor("#FF5252"), 2)
        p.setPen(pen)
        p.drawLine(cx - 8, cy, cx + 8, cy)
        p.drawLine(cx, cy - 8, cx, cy + 8)
        p.end()

    def mousePressEvent(self, e) -> None:  # noqa: N802
        if not self._pixmap or self._scale <= 0:
            return
        off_x = (self.width() - self._pixmap.width() * self._scale) / 2
        off_y = (self.height() - self._pixmap.height() * self._scale) / 2
        dev_x = int((e.position().x() - off_x) / self._scale)
        dev_y = int((e.position().y() - off_y) / self._scale)
        if 0 <= dev_x < self._pixmap.width() and 0 <= dev_y < self._pixmap.height():
            self._last_pos = (int(e.position().x()), int(e.position().y()))
            self.update()
            self.tapped.emit(dev_x, dev_y)
        super().mousePressEvent(e)


# ---------------- 日志视图 ----------------
class LogView(QPlainTextEdit):
    LEVEL_COLOR = {
        "info": theme.MUTED,
        "action": theme.ACCENT,
        "success": theme.SUCCESS,
        "warn": theme.WARN,
        "error": theme.ERROR,
    }

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("LogView")
        self.setReadOnly(True)
        self.setMaximumBlockCount(5000)

    def append_log(self, msg: str, level: str = "info") -> None:
        color = self.LEVEL_COLOR.get(level, theme.MUTED)
        ts = time.strftime("%H:%M:%S")
        self.appendHtml(
            f'<span style="color:{theme.MUTED}">[{ts}]</span> '
            f'<span style="color:{color}">{html.escape(msg)}</span>'
        )

    def clear_log(self) -> None:
        self.clear()
