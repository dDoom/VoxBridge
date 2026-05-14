"""Translate tab — the original VoxBridge functionality."""
from __future__ import annotations

from PySide6.QtWidgets import QTabWidget, QVBoxLayout, QWidget

# Import the original main window as a widget wrapper
from echopilot.core.app_translate import MainWindow as TranslateMainWindow


class TranslateTab(QWidget):
    """Wraps the original translation UI as a tab."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # The original MainWindow is a QMainWindow; we can't embed it directly.
        # Instead we extract its central widget and reparent it.
        self._original = TranslateMainWindow()
        central = self._original.centralWidget()
        if central:
            central.setParent(self)
            layout.addWidget(central)
        self._original.setCentralWidget(None)
        self._original.hide()

    def cleanup(self) -> None:
        """Forward closeEvent to the original window for proper shutdown."""
        if hasattr(self._original, 'closeEvent'):
            # simulate cleanup
            if self._original.runner is not None:
                self._original.runner.stop()
            self._original.route_a.stop_meter()
            self._original.route_b.stop_meter()
