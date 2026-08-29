"""全局主题：暗色现代风 + 豆包蓝紫渐变。"""
from __future__ import annotations

# ---- 调色板 ----
BG = "#0F1219"
PANEL = "#161B26"
CARD = "#1D2433"
BORDER = "#262F42"
TEXT = "#E9EDF5"
MUTED = "#8B95AB"
ACCENT = "#5B8CFF"
ACCENT2 = "#7B5BFF"
SUCCESS = "#3DD68C"
WARN = "#FFB84D"
ERROR = "#FF6B6B"

FONT_STACK = (
    "'Microsoft YaHei UI','Microsoft YaHei','PingFang SC','Noto Sans CJK SC',"
    "'Segoe UI',sans-serif"
)

QSS = f"""
* {{ font-family: {FONT_STACK}; font-size: 13px; color: {TEXT}; }}
QMainWindow, QDialog {{ background: {BG}; }}
QWidget {{ background: transparent; }}

/* 顶部标题 */
#HeaderBar {{ background: {PANEL}; border-bottom: 1px solid {BORDER}; }}
#AppTitle {{ font-size: 16px; font-weight: 700; color: {TEXT}; }}
#AppSubtitle {{ font-size: 11px; color: {MUTED}; }}
#LogoLabel {{ font-size: 20px; font-weight: 800; color: {ACCENT}; }}

/* 面板卡片 */
#DevicePanel, #RightPanel {{
  background: {PANEL}; border: 1px solid {BORDER}; border-radius: 12px;
}}
QFrame[card="true"] {{
  background: {CARD}; border: 1px solid {BORDER}; border-radius: 10px;
}}
QLabel[sectionTitle="true"] {{
  font-size: 12px; font-weight: 700; color: {MUTED};
  letter-spacing: 1px; padding: 2px 2px 6px 2px;
}}

/* 按钮 */
QPushButton {{
  background: {CARD}; border: 1px solid {BORDER}; border-radius: 8px;
  padding: 7px 16px; color: {TEXT};
}}
QPushButton:hover {{ border-color: {ACCENT}; color: {ACCENT}; }}
QPushButton:pressed {{ background: #242E44; }}
QPushButton:disabled {{ color: {MUTED}; border-color: {BORDER}; background: #181E2A; }}

QPushButton[primary="true"] {{
  background: qlineargradient(x1:0,y1:0,x2:1,y2:0, stop:0 {ACCENT}, stop:1 {ACCENT2});
  border: none; color: white; font-weight: 600;
}}
QPushButton[primary="true"]:hover {{ opacity: 0.9; border: none; color: white; }}

QPushButton[danger="true"] {{ color: {ERROR}; border-color: rgba(255,107,107,0.4); }}
QPushButton[danger="true"]:hover {{ background: rgba(255,107,107,0.12); }}

QPushButton[small="true"] {{ padding: 4px 10px; font-size: 12px; }}

/* 输入 */
QLineEdit, QPlainTextEdit, QSpinBox, QDoubleSpinBox, QComboBox {{
  background: {CARD}; border: 1px solid {BORDER}; border-radius: 8px;
  padding: 7px 10px; selection-background-color: {ACCENT};
}}
QLineEdit:focus, QPlainTextEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus, QComboBox:focus {{
  border-color: {ACCENT};
}}
QComboBox::drop-down {{ border: none; width: 24px; }}
QComboBox QAbstractItemView {{
  background: {CARD}; border: 1px solid {BORDER}; selection-background-color: {ACCENT};
}}

/* 状态胶囊 */
QFrame[pill="true"] {{
  background: {CARD}; border: 1px solid {BORDER}; border-radius: 14px;
}}
QLabel[pillDot="true"] {{ font-size: 14px; }}
QLabel[pillText="true"] {{ font-size: 12px; font-weight: 600; }}

/* 列表/日志 */
QTextEdit#LogView, QTextBrowser#ChatView {{
  background: {CARD}; border: 1px solid {BORDER}; border-radius: 10px;
}}
QTextEdit#LogView {{ font-family: Consolas, 'Courier New', monospace; font-size: 12px; }}

/* 滚动条 */
QScrollBar:vertical {{ background: transparent; width: 9px; margin: 2px; }}
QScrollBar::handle:vertical {{
  background: #2E3A52; border-radius: 4px; min-height: 30px;
}}
QScrollBar::handle:vertical:hover {{ background: {ACCENT}; }}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
QScrollBar:horizontal {{ background: transparent; height: 9px; margin: 2px; }}
QScrollBar::handle:horizontal {{ background: #2E3A52; border-radius: 4px; min-width: 30px; }}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{ width: 0; }}

/* 分割条 */
QSplitter::handle {{ background: {BG}; width: 6px; height: 6px; }}
QSplitter::handle:hover {{ background: {ACCENT}; }}

/* Tab */
QTabWidget::pane {{ border: none; }}
QTabBar::tab {{
  background: transparent; color: {MUTED}; padding: 8px 18px; border: none;
  border-bottom: 2px solid transparent; font-weight: 600;
}}
QTabBar::tab:selected {{ color: {TEXT}; border-bottom: 2px solid {ACCENT}; }}
QTabBar::tab:hover {{ color: {TEXT}; }}

/* 对话框 */
QDialog QLabel {{ color: {TEXT}; }}
QGroupBox {{
  border: 1px solid {BORDER}; border-radius: 10px; margin-top: 10px; padding-top: 8px;
}}
QGroupBox::title {{
  subcontrol-origin: margin; left: 10px; padding: 0 4px; color: {ACCENT};
  font-weight: 600;
}}
QCheckBox {{ spacing: 8px; }}
QCheckBox::indicator {{ width: 16px; height: 16px; border-radius: 4px;
  border: 1px solid {BORDER}; background: {CARD}; }}
QCheckBox::indicator:checked {{ background: {ACCENT}; border-color: {ACCENT}; }}

QToolTip {{
  background: {CARD}; color: {TEXT}; border: 1px solid {BORDER};
  border-radius: 6px; padding: 4px 8px;
}}
"""
