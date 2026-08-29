"""程序入口。"""
from __future__ import annotations

import sys
from pathlib import Path

# 兼容两种启动方式：
#   python -m app.main          （从项目根目录，标准方式）
#   python app/main.py / 双击    （直接运行脚本，需要把项目根目录加进搜索路径）
if __package__ in (None, ""):
    _root = Path(__file__).resolve().parent.parent
    if str(_root) not in sys.path:
        sys.path.insert(0, str(_root))


def _load_icon(app) -> None:
    """加载应用图标（优先打包资源，其次源码 assets）。"""
    try:
        from PySide6.QtGui import QIcon
        candidates = []
        if getattr(sys, "frozen", False):
            candidates.append(Path(sys.executable).parent / "assets" / "icon.ico")
        candidates.append(Path(__file__).resolve().parents[1] / "assets" / "icon.ico")
        candidates.append(Path(__file__).resolve().parents[1] / "assets" / "icon.png")
        for c in candidates:
            if c.exists():
                app.setWindowIcon(QIcon(str(c)))
                return
    except Exception:
        pass


def main() -> int:
    from PySide6.QtWidgets import QApplication

    from app.gui.main_window import MainWindow

    app = QApplication(sys.argv)
    app.setApplicationName("豆包手机助手")
    app.setStyle("Fusion")
    _load_icon(app)
    win = MainWindow()
    win.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
