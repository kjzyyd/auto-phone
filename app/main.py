"""程序入口。"""
from __future__ import annotations

import sys
from pathlib import Path


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
