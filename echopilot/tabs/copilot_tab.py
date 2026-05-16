"""Co-Pilot tab — AI hints based on pre-loaded context."""
from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path
from PySide6.QtCore import QObject, Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from echopilot.core.audio import list_audio_devices, list_loopback_devices
from echopilot.core.copilot import CoPilotConfig, CoPilotRunner, DEFAULT_COPILOT_MODEL
from echopilot.services.markdown_converter import MarkdownConverter
from echopilot.ui.hint_card import HintCard


class CoPilotSignals(QObject):
    status = Signal(str)
    transcript = Signal(str)
    hint = Signal(str, str)
    error = Signal(str)
    stopped = Signal()


class CoPilotTab(QWidget):
    """Upload context, get real-time AI hints in a scrollable feed."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._context_text: str = ""
        self._converter = MarkdownConverter()
        self._runner: CoPilotRunner | None = None
        self._signals = CoPilotSignals()
        self._setup_ui()
        self._connect_signals()
        self.refresh_devices()

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setSpacing(16)
        layout.setContentsMargins(16, 16, 16, 16)

        # --- Realtime listener configuration ---
        realtime_box = QGroupBox("Realtime Listener")
        realtime_layout = QFormLayout(realtime_box)
        realtime_layout.setSpacing(10)

        self._api_key = QLineEdit(os.getenv("OPENAI_API_KEY", ""))
        self._api_key.setEchoMode(QLineEdit.EchoMode.Password)
        self._api_key.setPlaceholderText("OpenAI API key")
        realtime_layout.addRow("API key", self._api_key)

        self._model_input = QLineEdit(DEFAULT_COPILOT_MODEL)
        self._model_input.setPlaceholderText(DEFAULT_COPILOT_MODEL)
        self._model_input.setReadOnly(True)
        realtime_layout.addRow("Realtime model", self._model_input)

        self._meeting_goal = QLineEdit()
        self._meeting_goal.setPlaceholderText("e.g. negotiate renewal terms, prepare objection handling")
        realtime_layout.addRow("Meeting goal", self._meeting_goal)

        device_row = QHBoxLayout()
        self._input_device = QComboBox()
        self._input_device.setMinimumWidth(360)
        device_row.addWidget(self._input_device, stretch=1)
        self._refresh_devices_btn = QPushButton("Refresh")
        self._refresh_devices_btn.clicked.connect(self.refresh_devices)
        device_row.addWidget(self._refresh_devices_btn)
        realtime_layout.addRow("Microphone", device_row)

        speaker_row = QHBoxLayout()
        self._speaker_device = QComboBox()
        self._speaker_device.setMinimumWidth(360)
        speaker_row.addWidget(self._speaker_device, stretch=1)
        realtime_layout.addRow("Meeting audio", speaker_row)

        self._listen_status = QLabel("Idle")
        self._listen_status.setStyleSheet("color:#94a3b8; font-size:12px;")
        realtime_layout.addRow("Status", self._listen_status)

        layout.addWidget(realtime_box)

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
        self._toggle_btn = QPushButton("Start Listening")
        self._toggle_btn.setCheckable(True)
        self._toggle_btn.setStyleSheet(
            "QPushButton { background:#22c55e; color:#000; border:none; border-radius:6px; "
            "padding:8px 18px; font-weight:600; }"
            "QPushButton:checked { background:#ef4444; }"
        )
        self._toggle_btn.toggled.connect(self._toggle_listening)
        controls.addWidget(self._toggle_btn)

        self._suggest_btn = QPushButton("Suggest now")
        self._suggest_btn.setToolTip("Ask for a hint using the conversation heard so far")
        self._suggest_btn.setEnabled(False)
        self._suggest_btn.clicked.connect(self._suggest_now)
        controls.addWidget(self._suggest_btn)
        controls.addStretch()

        self._hint_count = QLabel("0 hints")
        self._hint_count.setStyleSheet("color:#94a3b8; font-size:12px;")
        controls.addWidget(self._hint_count)

        self._clear_hints_btn = QPushButton("Clear")
        self._clear_hints_btn.setToolTip("Clear hint cards")
        self._clear_hints_btn.clicked.connect(self.clear_hints)
        controls.addWidget(self._clear_hints_btn)
        hint_layout.addLayout(controls)

        # Scroll area for cards
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setStyleSheet("QScrollArea { border:none; background:transparent; }")

        self._hint_container = QWidget()
        self._hint_layout = QVBoxLayout(self._hint_container)
        self._hint_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self._hint_layout.setSpacing(12)
        self._hint_layout.setContentsMargins(8, 8, 8, 8)
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

    # --- Realtime engine ---

    def _connect_signals(self) -> None:
        self._signals.status.connect(self._set_status)
        self._signals.transcript.connect(self.set_transcript)
        self._signals.hint.connect(self.add_hint)
        self._signals.error.connect(self._show_error)
        self._signals.stopped.connect(self._runner_stopped)

    def refresh_devices(self) -> None:
        selected = self._input_device.currentData()
        selected_speaker = self._speaker_device.currentData()
        had_speaker_selection = self._speaker_device.count() > 0
        self._input_device.clear()
        self._speaker_device.clear()
        try:
            devices = list_audio_devices()
            loopbacks = list_loopback_devices()
        except Exception as exc:  # noqa: BLE001
            self._set_status(f"Could not list audio devices: {exc}")
            return

        inputs = [device for device in devices if device.max_input_channels > 0]
        for device in inputs:
            self._input_device.addItem(device.label, device.index)

        if selected is not None:
            index = self._input_device.findData(selected)
            if index >= 0:
                self._input_device.setCurrentIndex(index)

        self._speaker_device.addItem("Disabled", None)
        for device in loopbacks:
            self._speaker_device.addItem(device.label, device.id)

        if selected_speaker is not None:
            index = self._speaker_device.findData(selected_speaker)
            if index >= 0:
                self._speaker_device.setCurrentIndex(index)
        elif not had_speaker_selection and loopbacks:
            self._speaker_device.setCurrentIndex(1)

        self._set_status(
            f"Found {len(inputs)} microphone input(s), {len(loopbacks)} meeting audio source(s)"
        )

    def _toggle_listening(self, checked: bool) -> None:
        if checked:
            self._start_listening()
        else:
            self._stop_listening()

    def _start_listening(self) -> None:
        if self._runner is not None:
            return

        api_key = self._api_key.text().strip()
        if not api_key:
            self._reset_toggle()
            QMessageBox.warning(self, "Co-Pilot", "Enter an OpenAI API key or set OPENAI_API_KEY.")
            return

        if self._input_device.currentData() is None:
            self._reset_toggle()
            QMessageBox.warning(self, "Co-Pilot", "Select a microphone input.")
            return

        config = CoPilotConfig(
            api_key=api_key,
            model=DEFAULT_COPILOT_MODEL,
            input_device=int(self._input_device.currentData()),
            speaker_device=self._speaker_device.currentData(),
            meeting_goal=self._meeting_goal.text().strip(),
            context=self._context_text,
        )

        self._runner = CoPilotRunner(
            config,
            on_status=self._signals.status.emit,
            on_transcript=self._signals.transcript.emit,
            on_hint=self._signals.hint.emit,
            on_error=self._signals.error.emit,
            on_stopped=self._signals.stopped.emit,
        )
        self._toggle_btn.setText("Stop Listening")
        self._api_key.setEnabled(False)
        self._model_input.setEnabled(False)
        self._meeting_goal.setEnabled(False)
        self._input_device.setEnabled(False)
        self._speaker_device.setEnabled(False)
        self._refresh_devices_btn.setEnabled(False)
        self._suggest_btn.setEnabled(True)
        self._set_status("Starting")
        self._runner.start()

    def _stop_listening(self) -> None:
        if self._runner is not None:
            self._set_status("Stopping")
            self._runner.stop()
        self._suggest_btn.setEnabled(False)
        self._toggle_btn.setEnabled(False)

    def _runner_stopped(self) -> None:
        self._runner = None
        self._toggle_btn.setEnabled(True)
        self._reset_toggle()
        self._api_key.setEnabled(True)
        self._model_input.setEnabled(True)
        self._meeting_goal.setEnabled(True)
        self._input_device.setEnabled(True)
        self._speaker_device.setEnabled(True)
        self._refresh_devices_btn.setEnabled(True)
        self._suggest_btn.setEnabled(False)

    def _reset_toggle(self) -> None:
        self._toggle_btn.blockSignals(True)
        self._toggle_btn.setChecked(False)
        self._toggle_btn.setText("Start Listening")
        self._toggle_btn.blockSignals(False)

    def _set_status(self, message: str) -> None:
        self._log(f"status: {message}")
        self._listen_status.setText(message)

    def _show_error(self, message: str) -> None:
        self._log(f"error:\n{message}")
        short = message.splitlines()[0] if message else "Unknown Co-Pilot error"
        self._set_status(f"Error: {short}")
        self.add_hint("alert", short)

    def _suggest_now(self) -> None:
        if self._runner is None:
            return
        self._set_status("Manual hint requested")
        self._runner.request_hint()

    def cleanup(self) -> None:
        if self._runner is not None:
            self._runner.stop()

    # --- Public API for the engine ---

    def set_transcript(self, text: str) -> None:
        self._transcript.setText(text)
        self._log(f"transcript: {text}")

    def add_hint(self, hint_type: str, text: str) -> None:
        """Called by the CoPilot engine when a new hint arrives."""
        self._log(f"hint[{hint_type}]: {text}")
        card = HintCard(hint_type, text)
        card.destroyed.connect(lambda: QTimer.singleShot(0, self._update_hint_count))
        # Insert before the stretch
        self._hint_layout.insertWidget(self._hint_layout.count() - 1, card)
        self._update_hint_count()

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

    def _update_hint_count(self) -> None:
        count = 0
        for i in range(self._hint_layout.count()):
            widget = self._hint_layout.itemAt(i).widget()
            if isinstance(widget, HintCard):
                count += 1
        self._hint_count.setText(f"{count} hint{'s' if count != 1 else ''}")

    @staticmethod
    def _log(message: str) -> None:
        timestamp = datetime.now().strftime("%H:%M:%S")
        print(f"[{timestamp}] [Co-Pilot] {message}", flush=True)
