"""Single hint card widget for Co-Pilot hints."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)


HINT_STYLES: dict[str, str] = {
    "argument": "background:#1a1a2e;border-left:3px solid #22c55e;color:#e2e8f0;",
    "fact": "background:#1a1a2e;border-left:3px solid #38bdf8;color:#e2e8f0;",
    "action": "background:#1a1a2e;border-left:3px solid #f59e0b;color:#e2e8f0;",
    "alert": "background:#1a1a2e;border-left:3px solid #ef4444;color:#e2e8f0;",
    "general": "background:#1a1a2e;border-left:3px solid #94a3b8;color:#e2e8f0;",
}

BADGE_TEXT: dict[str, str] = {
    "argument": "Argument",
    "fact": "Fact",
    "action": "Action",
    "alert": "Alert",
    "general": "Hint",
}


class HintCard(QFrame):
    """A dismissible card showing one AI hint."""

    def __init__(self, hint_type: str, text: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.hint_type = hint_type
        self.setObjectName("HintCard")
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.setMinimumWidth(0)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
        self.setStyleSheet(
            f"QFrame#HintCard {{ {HINT_STYLES.get(hint_type, HINT_STYLES['general'])} "
            "border-radius:8px; }"
        )

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 12)
        layout.setSpacing(8)

        header = QHBoxLayout()
        header.setSpacing(8)

        badge = QLabel(BADGE_TEXT.get(hint_type, BADGE_TEXT["general"]))
        badge.setTextFormat(Qt.TextFormat.PlainText)
        badge.setStyleSheet("font-size:11px;font-weight:600;color:#94a3b8;")
        header.addWidget(badge)
        header.addStretch()

        copy_btn = QPushButton("Copy")
        copy_btn.setToolTip("Copy to clipboard")
        copy_btn.setStyleSheet(
            "QPushButton { background:transparent;border:none;color:#94a3b8;font-size:11px; }"
            "QPushButton:hover { color:#22c55e; }"
        )
        copy_btn.setFixedSize(38, 24)
        copy_btn.clicked.connect(self._copy)
        header.addWidget(copy_btn)

        dismiss_btn = QPushButton("x")
        dismiss_btn.setToolTip("Dismiss")
        dismiss_btn.setStyleSheet(
            "QPushButton { background:transparent;border:none;color:#94a3b8;font-size:13px; }"
            "QPushButton:hover { color:#ef4444; }"
        )
        dismiss_btn.setFixedSize(24, 24)
        dismiss_btn.clicked.connect(self.deleteLater)
        header.addWidget(dismiss_btn)

        layout.addLayout(header)

        body = QLabel(text)
        body.setTextFormat(Qt.TextFormat.PlainText)
        body.setWordWrap(True)
        body.setMinimumWidth(0)
        body.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
        body.setStyleSheet("font-size:13px;color:#e2e8f0;")
        body.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(body)

        self._body = body

    def _copy(self) -> None:
        QApplication.clipboard().setText(self._body.text())
