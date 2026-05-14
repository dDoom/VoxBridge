"""Mobile tab — Twilio integration for phone call translation."""
from __future__ import annotations

from PySide6.QtWidgets import (
    QComboBox,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)


class MobileTab(QWidget):
    """Twilio configuration and call history."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._setup_ui()

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setSpacing(16)
        layout.setContentsMargins(16, 16, 16, 16)

        # --- Connection ---
        conn = QGroupBox("Twilio Configuration")
        c_layout = QVBoxLayout(conn)
        c_layout.setSpacing(10)

        # Account SID
        sid_row = QHBoxLayout()
        sid_row.addWidget(QLabel("Account SID:"))
        self._sid = QLineEdit()
        self._sid.setEchoMode(QLineEdit.EchoMode.Password)
        self._sid.setPlaceholderText("ACxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx")
        sid_row.addWidget(self._sid)
        c_layout.addLayout(sid_row)

        # Auth Token
        token_row = QHBoxLayout()
        token_row.addWidget(QLabel("Auth Token:"))
        self._token = QLineEdit()
        self._token.setEchoMode(QLineEdit.EchoMode.Password)
        self._token.setPlaceholderText("your_auth_token")
        token_row.addWidget(self._token)
        c_layout.addLayout(token_row)

        # Verify row
        verify_row = QHBoxLayout()
        self._verify_btn = QPushButton("🔑 Verify & Connect")
        self._verify_btn.setStyleSheet(
            "QPushButton { background:#22c55e; color:#000; border:none; border-radius:6px; "
            "padding:8px 18px; font-weight:600; }"
            "QPushButton:hover { background:#2dd264; }"
        )
        verify_row.addWidget(self._verify_btn)
        self._status = QLabel("🔴 Not connected")
        self._status.setStyleSheet("color:#ef4444; font-size:13px;")
        verify_row.addWidget(self._status)
        verify_row.addStretch()
        c_layout.addLayout(verify_row)
        layout.addWidget(conn)

        # --- Number management ---
        num = QGroupBox("My Twilio Number")
        n_layout = QVBoxLayout(num)

        num_row = QHBoxLayout()
        num_row.addWidget(QLabel("Number:"))
        self._number = QLabel("—")
        self._number.setStyleSheet("font-size:14px; font-weight:600; color:#e2e8f0;")
        num_row.addWidget(self._number)
        num_row.addStretch()

        self._buy_btn = QPushButton("Buy New Number")
        self._buy_btn.setEnabled(False)
        num_row.addWidget(self._buy_btn)

        self._release_btn = QPushButton("Release")
        self._release_btn.setEnabled(False)
        num_row.addWidget(self._release_btn)
        n_layout.addLayout(num_row)

        # Forwarding instructions
        fwd = QLabel(
            "To enable call forwarding:\n"
            "1. On your phone dial: *72 followed by your Twilio number\n"
            "2. Wait for confirmation tone\n"
            "3. All calls will now route through EchoPilot"
        )
        fwd.setStyleSheet("color:#94a3b8; font-size:12px; padding:8px; background:#12121a; border-radius:6px;")
        fwd.setWordWrap(True)
        n_layout.addWidget(fwd)

        self._copy_fwd = QPushButton("📋 Copy forwarding code")
        self._copy_fwd.setEnabled(False)
        n_layout.addWidget(self._copy_fwd)
        layout.addWidget(num)

        # --- Call history ---
        hist = QGroupBox("Call History")
        h_layout = QVBoxLayout(hist)
        self._table = QTableWidget()
        self._table.setColumnCount(5)
        self._table.setHorizontalHeaderLabels(["Time", "From", "To", "Duration", "Cost"])
        self._table.setStyleSheet("QTableWidget { background:#12121a; border:none; }")
        h_layout.addWidget(self._table)
        layout.addWidget(hist, stretch=1)

        # --- Balance ---
        bal = QGroupBox("Balance")
        b_layout = QHBoxLayout(bal)
        self._balance = QLabel("$0.00")
        self._balance.setStyleSheet("font-size:16px; font-weight:700; color:#22c55e;")
        b_layout.addWidget(self._balance)
        self._refresh_bal = QPushButton("🔄 Refresh")
        b_layout.addWidget(self._refresh_bal)
        b_layout.addStretch()
        layout.addWidget(bal)

        layout.addStretch()
