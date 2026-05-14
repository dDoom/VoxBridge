from __future__ import annotations

import sys

from PySide6.QtWidgets import QApplication

from .app import MainWindow


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("VoxBridge")
    app.setOrganizationName("VoxBridge")
    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
