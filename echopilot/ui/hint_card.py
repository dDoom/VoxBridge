"""Single hint card widget for Co-Pilot hints."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)


HINT_STYLES: dict[str, str] = {
    "argument": "background:#1a1a2e;border-left:3px solid #22c55e;color:#e2e8f0;",
    "fact":     "background:#1a1a2e;border-left:3px solid #38bdf8;color:#e2e8f0;",
    "action":   "background:#1a1a2e;border-left:3px solid #f59e0b;color:#e2e8f0;",
    "alert":    "background:#1a1a2e;border-left:3px solid #ef4444;color:#e2e8f0;",
    "general":  "background:#1a1a2e;border-left:3px solid #94a3b8;color:#e2e8f0;",
}

BADGE_TEXT: dict[str, str] = {
    "argument": "💡 Argument",
    "fact":     "📊 Fact",
    "action":   "⚡ Action",
    "alert":    "🚨 Alert",
    "general":  "💭 Hint",
}


class HintCard(QFrame):
    """A dismissible card showing one AI hint."""

    def __init__(self, hint_type: str, text: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.hint_type = hint_type
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.setStyleSheet(
            f"HintCard {{ {HINT_STYLES.get(hint_type, HINT_STYLES['general'])} "
            f"border-radius:8px;padding:10px;margin:4px 0; }}"
        )
        self.setMaximumWidth(480)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(6)

        # Header with badge and dismiss
        header = QHBoxLayout()
        header.setSpacing(8)

        badge = QLabel(BADGE_TEXT.get(hint_type, BADGE_TEXT["general"]))
        badge.setStyleSheet("font-size:11px;font-weight:600;color:#94a3b8;")
        header.addWidget(badge)
        header.addStretch()

        copy_btn = QPushButton("📋")
        copy_btn.setToolTip("Copy to clipboard")
        copy_btn.setStyleSheet(
            "QPushButton { background:transparent;border:none;color:#94a3b8;font-size:13px; }"
            "QPushButton:hover { color:#22c55e; }"
        )
        copy_btn.setFixedSize(24, 24)
        copy_btn.clicked.connect(self._copy)
        header.addWidget(copy_btn)

        dismiss_btn = QPushButton("✕")
        dismiss_btn.setToolTip("Dismiss")
        dismiss_btn.setStyleSheet(
            "QPushButton { background:transparent;border:none;color:#94a3b8;font-size:13px; }"
            "QPushButton:hover { color:#ef4444; }"
        )
        dismiss_btn.setFixedSize(24, 24)
        dismiss_btn.clicked.connect(self.deleteLater)
        header.addWidget(dismiss_btn)

        layout.addLayout(header)

        # Body
        body = QLabel(text)
        body.setWordWrap(True)
        body.setStyleSheet("font-size:13px;line-height:1.4;")
        body.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(body)

        self._body = body

    def _copy(self) -> None:
        from PySide6.QtWidgets import QApplication
        QApplication.clipboard().setText(self._body.text())
