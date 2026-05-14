"""Co-Pilot tab — AI hints based on pre-loaded context."""
from __future__ import annotations

from pathlib import Path
from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QFileDialog,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from echopilot.services.markdown_converter import MarkdownConverter
from echopilot.ui.hint_card import HintCard


class CoPilotTab(QWidget):
    """Upload context, get real-time AI hints in a scrollable feed."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._context_text: str = ""
        self._converter = MarkdownConverter()
        self._setup_ui()

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setSpacing(16)
        layout.setContentsMargins(16, 16, 16, 16)

        # --- Context upload section ---
        upload_box = QGroupBox("Context Upload")
        upload_layout = QVBoxLayout(upload_box)
        upload_layout.setSpacing(10)

        # Drag-and-drop zone
        self._drop_zone = QLabel("📎 Drop PDF / DOCX / TXT files here, or click Browse")
        self._drop_zone.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._drop_zone.setStyleSheet(
            "QLabel { background:#12121a; border:2px dashed #2a2a3d; border-radius:8px; "
            "padding:20px; color:#94a3b8; font-size:13px; }"
            "QLabel:hover { border-color:#22c55e; }"
        )
        self._drop_zone.setMinimumHeight(80)
        self._drop_zone.setAcceptDrops(True)
        self._drop_zone.dragEnterEvent = self._drag_enter
        self._drop_zone.dropEvent = self._drop
        upload_layout.addWidget(self._drop_zone)

        # URL row
        url_row = QHBoxLayout()
        self._url_input = QLineEdit()
        self._url_input.setPlaceholderText("https://example.com/docs ...")
        self._url_input.setStyleSheet("QLineEdit { min-height:30px; padding:0 10px; }")
        url_row.addWidget(self._url_input)

        self._fetch_btn = QPushButton("Fetch URL")
        self._fetch_btn.setStyleSheet(
            "QPushButton { background:#22c55e; color:#000; border:none; border-radius:6px; "
            "padding:6px 14px; font-weight:600; }"
            "QPushButton:hover { background:#2dd264; }"
        )
        self._fetch_btn.clicked.connect(self._fetch_url)
        url_row.addWidget(self._fetch_btn)
        upload_layout.addLayout(url_row)

        # Browse button row
        btn_row = QHBoxLayout()
        self._browse_btn = QPushButton("📁 Browse files...")
        self._browse_btn.clicked.connect(self._browse_files)
        btn_row.addWidget(self._browse_btn)
        btn_row.addStretch()

        self._context_status = QLabel("No context loaded")
        self._context_status.setStyleSheet("color:#94a3b8; font-size:12px;")
        btn_row.addWidget(self._context_status)
        upload_layout.addLayout(btn_row)

        # Clear context
        self._clear_btn = QPushButton("🗑 Clear")
        self._clear_btn.clicked.connect(self._clear_context)
        self._clear_btn.setEnabled(False)
        btn_row.addWidget(self._clear_btn)

        layout.addWidget(upload_box)

        # --- Hint feed ---
        hint_box = QGroupBox("Live Hints")
        hint_layout = QVBoxLayout(hint_box)
        hint_layout.setSpacing(8)
        hint_layout.setContentsMargins(10, 14, 10, 10)

        # Controls
        controls = QHBoxLayout()
        self._toggle_btn = QPushButton("▶ Start Listening")
        self._toggle_btn.setCheckable(True)
        self._toggle_btn.setStyleSheet(
            "QPushButton { background:#22c55e; color:#000; border:none; border-radius:6px; "
            "padding:8px 18px; font-weight:600; }"
            "QPushButton:checked { background:#ef4444; }"
        )
        controls.addWidget(self._toggle_btn)
        controls.addStretch()

        self._hint_count = QLabel("0 hints")
        self._hint_count.setStyleSheet("color:#94a3b8; font-size:12px;")
        controls.addWidget(self._hint_count)
        hint_layout.addLayout(controls)

        # Scroll area for cards
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setStyleSheet("QScrollArea { border:none; background:transparent; }")

        self._hint_container = QWidget()
        self._hint_layout = QVBoxLayout(self._hint_container)
        self._hint_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self._hint_layout.setSpacing(6)
        self._hint_layout.setContentsMargins(4, 4, 4, 4)
        self._hint_layout.addStretch()
        scroll.setWidget(self._hint_container)
        hint_layout.addWidget(scroll)

        layout.addWidget(hint_box, stretch=1)

        # --- Transcript mini panel ---
        trans_box = QGroupBox("Live Transcript")
        trans_layout = QVBoxLayout(trans_box)
        self._transcript = QLabel("Waiting for conversation...")
        self._transcript.setWordWrap(True)
        self._transcript.setStyleSheet("color:#94a3b8; font-size:12px; max-height:60px;")
        trans_layout.addWidget(self._transcript)
        layout.addWidget(trans_box)

    # --- Drag and drop ---

    def _drag_enter(self, event) -> None:
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def _drop(self, event) -> None:
        urls = event.mimeData().urls()
        paths = [Path(u.toLocalFile()) for u in urls if u.isLocalFile()]
        self._load_files(paths)

    def _browse_files(self) -> None:
        files, _ = QFileDialog.getOpenFileNames(
            self, "Select context files", "",
            "Documents (*.pdf *.docx *.doc *.txt *.md);;All files (*.*)"
        )
        if files:
            self._load_files([Path(f) for f in files])

    def _load_files(self, paths: list[Path]) -> None:
        parts = []
        for p in paths:
            md = self._converter.convert(p)
            parts.append(f"\n## Source: {p.name}\n\n{md}\n")
        self._context_text = "\n".join(parts)
        self._drop_zone.setText(f"✅ Loaded {len(paths)} file(s)")
        self._drop_zone.setStyleSheet(
            "QLabel { background:#12121a; border:2px solid #22c55e; border-radius:8px; "
            "padding:20px; color:#22c55e; font-size:13px; }"
        )
        self._context_status.setText(f"Context: {len(self._context_text)} chars | {len(paths)} files")
        self._clear_btn.setEnabled(True)

    def _fetch_url(self) -> None:
        url = self._url_input.text().strip()
        if not url:
            return
        self._fetch_btn.setEnabled(False)
        self._fetch_btn.setText("Fetching...")
        text = self._converter.url_to_markdown(url)
        self._context_text += f"\n\n## URL: {url}\n\n{text}\n"
        self._context_status.setText(f"Context: {len(self._context_text)} chars | URL added")
        self._fetch_btn.setEnabled(True)
        self._fetch_btn.setText("Fetch URL")
        self._clear_btn.setEnabled(True)

    def _clear_context(self) -> None:
        self._context_text = ""
        self._drop_zone.setText("📎 Drop PDF / DOCX / TXT files here, or click Browse")
        self._drop_zone.setStyleSheet(
            "QLabel { background:#12121a; border:2px dashed #2a2a3d; border-radius:8px; "
            "padding:20px; color:#94a3b8; font-size:13px; }"
            "QLabel:hover { border-color:#22c55e; }"
        )
        self._context_status.setText("No context loaded")
        self._clear_btn.setEnabled(False)

    # --- Public API for the engine ---

    def set_transcript(self, text: str) -> None:
        self._transcript.setText(text)

    def add_hint(self, hint_type: str, text: str) -> None:
        """Called by the CoPilot engine when a new hint arrives."""
        card = HintCard(hint_type, text)
        # Insert before the stretch
        self._hint_layout.insertWidget(self._hint_layout.count() - 1, card)
        self._hint_count.setText(f"{self._hint_layout.count() - 2} hints")
        # Auto-dismiss after 30s
        QTimer.singleShot(30000, card.deleteLater)

    def context(self) -> str:
        return self._context_text

    def is_listening(self) -> bool:
        return self._toggle_btn.isChecked()

    def clear_hints(self) -> None:
        while self._hint_layout.count() > 1:
            item = self._hint_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self._hint_count.setText("0 hints")
