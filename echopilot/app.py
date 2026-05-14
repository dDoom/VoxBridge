"""EchoPilot main application — tabbed UI with Translate, Co-Pilot, Avatar, Mobile, Settings."""
from __future__ import annotations

import os
import sys
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (
    QApplication,
    QMainWindow,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from echopilot.tabs.translate_tab import TranslateTab
from echopilot.tabs.copilot_tab import CoPilotTab
from echopilot.tabs.avatar_tab import AvatarTab
from echopilot.tabs.mobile_tab import MobileTab


def get_asset_path(filename: str) -> str:
    """Get absolute path to asset, works for dev and for PyInstaller."""
    if hasattr(sys, "_MEIPASS"):
        return os.path.join(sys._MEIPASS, "assets", filename)
    return os.path.join(os.path.dirname(__file__), "..", "assets", filename)


class MainWindow(QMainWindow):
    """EchoPilot main window with tabbed interface."""

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("EchoPilot — AI Companion for Calls")
        self.setMinimumSize(900, 680)
        self.resize(1100, 800)

        # Central widget with tabs
        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.tabs = QTabWidget()
        self.tabs.setDocumentMode(True)
        self.tabs.setStyleSheet(
            """
            QTabWidget::pane { border:none; background:#0a0a0f; }
            QTabBar::tab {
                background:#12121a; color:#94a3b8; padding:10px 24px;
                border:none; font-size:13px; font-weight:500;
            }
            QTabBar::tab:selected { background:#0a0a0f; color:#22c55e; border-bottom:2px solid #22c55e; }
            QTabBar::tab:hover { color:#e2e8f0; }
            """
        )

        # Tabs
        self._translate_tab = TranslateTab()
        self._copilot_tab = CoPilotTab()
        self._avatar_tab = AvatarTab()
        self._mobile_tab = MobileTab()

        self.tabs.addTab(self._translate_tab, "🌐 Translate")
        self.tabs.addTab(self._copilot_tab, "💡 Co-Pilot")
        self.tabs.addTab(self._avatar_tab, "📷 Avatar")
        self.tabs.addTab(self._mobile_tab, "📱 Mobile")

        layout.addWidget(self.tabs)

        # Status bar
        self.statusBar().setStyleSheet(
            "QStatusBar { background:#12121a; color:#94a3b8; font-size:12px; padding:4px 12px; border-top:1px solid #1e1e2d; }"
        )
        self.statusBar().showMessage("EchoPilot ready — select a tab to begin")

    def closeEvent(self, event) -> None:  # noqa: ANN001, N802
        self._translate_tab.cleanup()
        super().closeEvent(event)


def main() -> None:
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    app.setStyleSheet(
        """
        QWidget { font-family: 'Inter', 'Segoe UI', system-ui, sans-serif; }
        QMainWindow { background:#0a0a0f; }
        QGroupBox {
            color:#e2e8f0; font-weight:600; font-size:13px;
            border:1px solid #1e1e2d; border-radius:10px; margin-top:8px; padding-top:8px;
        }
        QGroupBox::title { subcontrol-origin:margin; left:10px; padding:0 6px; }
        QLabel { color:#e2e8f0; }
        QLineEdit, QComboBox {
            background:#12121a; color:#e2e8f0; border:1px solid #2a2a3d;
            border-radius:6px; padding:6px 10px; min-height:28px;
        }
        QLineEdit:focus, QComboBox:focus { border-color:#22c55e; }
        QPushButton {
            background:#12121a; color:#e2e8f0; border:1px solid #2a2a3d;
            border-radius:6px; padding:6px 14px; font-weight:500;
        }
        QPushButton:hover { border-color:#22c55e; color:#22c55e; }
        QScrollArea { border:none; }
        """
    )
    win = MainWindow()
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
