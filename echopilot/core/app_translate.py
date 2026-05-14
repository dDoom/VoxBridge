from __future__ import annotations

import os
import sys
from datetime import datetime

import numpy as np
import sounddevice as sd
from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFormLayout,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QPlainTextEdit,
    QProgressBar,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from echopilot.core.audio import AudioDevice, list_audio_devices
from echopilot.core.bridge import BridgeRunner
from echopilot.core.config import DEFAULT_MODEL, TRANSLATION_LANGUAGES, BridgeConfig, RouteConfig


SOURCE_LANGUAGES = [("Auto detect", "auto"), *TRANSLATION_LANGUAGES]


def get_asset_path(filename: str) -> str:
    """Get absolute path to asset, works for dev and for PyInstaller"""
    if hasattr(sys, '_MEIPASS'):
        return os.path.join(sys._MEIPASS, "assets", filename)
    return os.path.join(os.path.dirname(__file__), "..", "assets", filename)


class BridgeSignals(QObject):
    status = Signal(str)
    transcript = Signal(str, str, str, bool)
    error = Signal(str)
    stopped = Signal()


class InputLevelMonitor(QObject):
    level_changed = Signal(int)
    state_changed = Signal(str)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._stream: sd.RawInputStream | None = None
        self._device_index: int | None = None

    def start(self, device_index: int | None) -> None:
        self.stop()
        if device_index is None:
            self.level_changed.emit(0)
            self.state_changed.emit("No input selected")
            return

        self._device_index = device_index
        try:
            device = sd.query_devices(device_index)
            sample_rate = int(device["default_samplerate"])
            blocksize = max(480, int(sample_rate * 0.05))

            def callback(indata, frames, time, status) -> None:  # noqa: ANN001, ARG001
                if status:
                    self.state_changed.emit(str(status))
                samples = np.frombuffer(bytes(indata), dtype="<i2").astype(np.float32)
                if samples.size == 0:
                    self.level_changed.emit(0)
                    return
                normalized = samples / 32768.0
                rms = float(np.sqrt(np.mean(normalized * normalized)))
                db = 20.0 * np.log10(max(rms, 0.000001))
                value = int(np.clip((db + 60.0) * 100.0 / 60.0, 0.0, 100.0))
                self.level_changed.emit(value)

            self._stream = sd.RawInputStream(
                samplerate=sample_rate,
                blocksize=blocksize,
                device=device_index,
                channels=1,
                dtype="int16",
                callback=callback,
            )
            self._stream.start()
            self.state_changed.emit("Input meter active")
        except Exception as exc:  # noqa: BLE001
            self._stream = None
            self.level_changed.emit(0)
            self.state_changed.emit(f"Meter unavailable: {exc}")

    def stop(self) -> None:
        if self._stream is not None:
            self._stream.stop()
            self._stream.close()
            self._stream = None
        self.level_changed.emit(0)


class RouteWidget(QGroupBox):
    def __init__(self, title: str, route_name: str, parent: QWidget | None = None) -> None:
        super().__init__(title, parent)
        self.route_name = route_name
        self.enabled = QCheckBox("Enabled")
        self.enabled.setChecked(True)
        self.audio_output_enabled = QCheckBox("Play translated audio")
        self.audio_output_enabled.setChecked(True)
        self.original_audio_volume = QSpinBox()
        self.original_audio_volume.setRange(0, 100)
        self.original_audio_volume.setSuffix("%")
        self.original_audio_volume.setValue(0)
        self.input_device = QComboBox()
        self.output_device = QComboBox()
        self.output_label = QLabel("Play to")
        self.source_language = QComboBox()
        self.target_language = QComboBox()
        self.level_meter = QProgressBar()
        self.level_meter.setRange(0, 100)
        self.level_meter.setTextVisible(False)
        self.level_meter.setFixedHeight(14)
        self.level_status = QLabel("No input selected")
        self.level_status.setObjectName("LevelStatus")
        self.level_monitor = InputLevelMonitor(self)
        for label, code in SOURCE_LANGUAGES:
            self.source_language.addItem(label, code)
        for label, code in TRANSLATION_LANGUAGES:
            self.target_language.addItem(label, code)

        layout = QFormLayout(self)
        layout.addRow(self.enabled)
        layout.addRow("Capture from", self.input_device)
        layout.addRow("Input level", self.level_meter)
        layout.addRow("", self.level_status)
        layout.addRow(self.audio_output_enabled)
        layout.addRow("Original passthrough", self.original_audio_volume)
        layout.addRow(self.output_label, self.output_device)
        layout.addRow("Source language", self.source_language)
        layout.addRow("Target language", self.target_language)
        self.level_monitor.level_changed.connect(self.level_meter.setValue)
        self.level_monitor.state_changed.connect(self.level_status.setText)
        self.input_device.currentIndexChanged.connect(self.restart_meter)
        self.audio_output_enabled.toggled.connect(self._audio_output_toggled)
        self.original_audio_volume.valueChanged.connect(self._sync_output_controls)
        self._sync_output_controls()

    def set_devices(self, inputs: list[AudioDevice], outputs: list[AudioDevice]) -> None:
        selected_input = self.input_device.currentData()
        selected_output = self.output_device.currentData()

        self.input_device.clear()
        for device in inputs:
            self.input_device.addItem(device.label, device.index)

        self.output_device.clear()
        for device in outputs:
            self.output_device.addItem(device.label, device.index)

        self._restore_selection(self.input_device, selected_input)
        self._restore_selection(self.output_device, selected_output)
        self.restart_meter()

    def restart_meter(self) -> None:
        current = self.input_device.currentData()
        self.level_monitor.start(None if current is None else int(current))

    def stop_meter(self) -> None:
        self.level_monitor.stop()
        self.level_status.setText("Input meter paused")

    def config(self) -> RouteConfig:
        enabled = self.enabled.isChecked()
        if not enabled:
            return RouteConfig(
                name=self.route_name,
                enabled=False,
                input_device=int(self.input_device.currentData() or -1),
                output_device=(
                    int(self.output_device.currentData())
                    if self.output_device.currentData() is not None
                    else None
                ),
                audio_output_enabled=self.audio_output_enabled.isChecked(),
                original_audio_volume=self.original_audio_volume.value(),
                source_language=str(self.source_language.currentData()),
                target_language=str(self.target_language.currentData()),
            )

        if self.input_device.currentData() is None:
            raise ValueError(f"{self.route_name}: select an input device")
        audio_output_enabled = self.audio_output_enabled.isChecked()
        original_audio_volume = self.original_audio_volume.value()
        needs_output = audio_output_enabled or original_audio_volume > 0
        if needs_output and self.output_device.currentData() is None:
            raise ValueError(f"{self.route_name}: select an output device")

        return RouteConfig(
            name=self.route_name,
            enabled=enabled,
            input_device=int(self.input_device.currentData()),
            output_device=(
                int(self.output_device.currentData())
                if needs_output and self.output_device.currentData() is not None
                else None
            ),
            audio_output_enabled=audio_output_enabled,
            original_audio_volume=original_audio_volume,
            source_language=str(self.source_language.currentData()),
            target_language=str(self.target_language.currentData()),
        )

    @staticmethod
    def _restore_selection(combo: QComboBox, value: int | None) -> None:
        if value is None:
            return
        index = combo.findData(value)
        if index >= 0:
            combo.setCurrentIndex(index)

    def _sync_output_controls(self) -> None:
        needs_output = (
            self.audio_output_enabled.isChecked()
            or self.original_audio_volume.value() > 0
        )
        self.output_label.setEnabled(needs_output)
        self.output_device.setEnabled(needs_output)

    def _audio_output_toggled(self, checked: bool) -> None:
        if not checked and self.original_audio_volume.value() == 0:
            self.original_audio_volume.setValue(100)
        self._sync_output_controls()


class TranscriptWidget(QGroupBox):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__("Transcripts", parent)
        self._history: dict[str, list[str]] = {"A": [], "B": []}
        self._partials: dict[tuple[str, str], str] = {}
        self.route_a = QPlainTextEdit()
        self.route_b = QPlainTextEdit()
        for editor in (self.route_a, self.route_b):
            editor.setReadOnly(True)
            editor.setMaximumBlockCount(800)
            editor.setPlaceholderText("Transcript will appear here while translation is running.")

        self.clear_button = QPushButton("Clear transcripts")
        self.clear_button.clicked.connect(self.clear)

        header = QHBoxLayout()
        header.addStretch(1)
        header.addWidget(self.clear_button)

        columns = QGridLayout()
        columns.setHorizontalSpacing(14)
        columns.addWidget(QLabel("Direction A"), 0, 0)
        columns.addWidget(QLabel("Direction B"), 0, 1)
        columns.addWidget(self.route_a, 1, 0)
        columns.addWidget(self.route_b, 1, 1)

        layout = QVBoxLayout(self)
        layout.addLayout(header)
        layout.addLayout(columns)

    def add_delta(self, route: str, kind: str, text: str, final: bool) -> None:
        route = route if route in self._history else "A"
        key = (route, kind)
        if final:
            partial = self._partials.pop(key, "").strip()
            content = text.strip()
            if partial and content and partial not in content and content not in partial:
                content = f"{partial} {content}".strip()
            elif not content:
                content = partial
            if content:
                self._history[route].append(f"{self._label(kind)}: {content}")
        else:
            self._partials[key] = self._partials.get(key, "") + text
        self._render(route)

    def clear(self) -> None:
        self._history = {"A": [], "B": []}
        self._partials.clear()
        self.route_a.clear()
        self.route_b.clear()

    def _render(self, route: str) -> None:
        lines = list(self._history[route])
        for kind in ("source", "translation"):
            partial = self._partials.get((route, kind), "").strip()
            if partial:
                lines.append(f"{self._label(kind)}: {partial}")

        editor = self.route_a if route == "A" else self.route_b
        scrollbar = editor.verticalScrollBar()
        at_bottom = scrollbar.value() >= scrollbar.maximum() - 4
        editor.setPlainText("\n\n".join(lines))
        if at_bottom:
            scrollbar.setValue(scrollbar.maximum())

    @staticmethod
    def _label(kind: str) -> str:
        return "Translation" if kind == "translation" else "Source"


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("VoxBridge")
        self.setWindowIcon(QIcon(get_asset_path("icon.png")))
        self.resize(980, 720)
        self.signals = BridgeSignals()
        self.signals.status.connect(self._append_status)
        self.signals.transcript.connect(self._append_transcript)
        self.signals.error.connect(self._show_error)
        self.signals.stopped.connect(self._runner_stopped)
        self.runner: BridgeRunner | None = None

        self.api_key = QLineEdit(os.getenv("OPENAI_API_KEY", ""))
        self.api_key.setEchoMode(QLineEdit.Password)
        self.model = QLineEdit(DEFAULT_MODEL)

        self.route_a = RouteWidget("Direction A", "A")
        self.route_b = RouteWidget("Direction B", "B")
        self.route_a.source_language.setCurrentIndex(self.route_a.source_language.findData("auto"))
        self.route_a.target_language.setCurrentIndex(self.route_a.target_language.findData("ru"))
        self.route_b.source_language.setCurrentIndex(self.route_b.source_language.findData("auto"))
        self.route_b.target_language.setCurrentIndex(self.route_b.target_language.findData("en"))

        self.refresh_button = QPushButton("Refresh devices")
        self.start_button = QPushButton("Start")
        self.stop_button = QPushButton("Stop")
        self.stop_button.setEnabled(False)
        self.transcripts = TranscriptWidget()
        self.status_log = QPlainTextEdit()
        self.status_log.setReadOnly(True)

        self._build_ui()
        self._connect_signals()
        self.refresh_devices()

    def _build_ui(self) -> None:
        central = QWidget()
        self.setCentralWidget(central)

        root = QVBoxLayout(central)
        root.setContentsMargins(20, 20, 20, 20)
        root.setSpacing(14)

        title = QLabel("VoxBridge")
        title.setObjectName("Title")
        title.setAlignment(Qt.AlignLeft)
        root.addWidget(title)

        api_group = QGroupBox("OpenAI")
        api_layout = QFormLayout(api_group)
        api_layout.addRow("API key", self.api_key)
        api_layout.addRow("Translation model", self.model)
        root.addWidget(api_group)

        route_layout = QGridLayout()
        route_layout.setHorizontalSpacing(14)
        route_layout.addWidget(self.route_a, 0, 0)
        route_layout.addWidget(self.route_b, 0, 1)
        root.addLayout(route_layout)

        buttons = QHBoxLayout()
        buttons.addWidget(self.refresh_button)
        buttons.addStretch(1)
        buttons.addWidget(self.start_button)
        buttons.addWidget(self.stop_button)
        root.addLayout(buttons)

        line = QFrame()
        line.setFrameShape(QFrame.HLine)
        root.addWidget(line)

        root.addWidget(self.transcripts, stretch=2)
        root.addWidget(QLabel("Status"))
        root.addWidget(self.status_log, stretch=1)

        self.setStyleSheet(
            """
            QWidget {
                font-size: 14px;
            }
            QLabel#Title {
                font-size: 28px;
                font-weight: 700;
            }
            QGroupBox {
                font-weight: 600;
                border: 1px solid palette(mid);
                border-radius: 8px;
                margin-top: 10px;
                padding: 12px;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 4px;
            }
            QPushButton {
                min-height: 34px;
                padding: 0 16px;
            }
            QComboBox, QLineEdit, QSpinBox {
                min-height: 30px;
            }
            QComboBox:disabled {
                color: palette(mid);
                background: palette(window);
            }
            QLabel:disabled {
                color: palette(mid);
            }
            QProgressBar {
                border: 1px solid palette(mid);
                border-radius: 4px;
                background: palette(base);
            }
            QProgressBar::chunk {
                background-color: #28a745;
                border-radius: 3px;
            }
            QPlainTextEdit {
                font-family: Consolas, "Cascadia Mono", monospace;
            }
            QLabel#LevelStatus {
                color: palette(mid);
                font-size: 12px;
            }
            """
        )

    def _connect_signals(self) -> None:
        self.refresh_button.clicked.connect(self.refresh_devices)
        self.start_button.clicked.connect(self.start_bridge)
        self.stop_button.clicked.connect(self.stop_bridge)

    def refresh_devices(self) -> None:
        try:
            devices = list_audio_devices()
        except Exception as exc:  # noqa: BLE001
            self._show_error(f"Could not list audio devices: {exc}")
            return

        inputs = [device for device in devices if device.max_input_channels > 0]
        outputs = [device for device in devices if device.max_output_channels > 0]
        self.route_a.set_devices(inputs, outputs)
        self.route_b.set_devices(inputs, outputs)
        self._append_status(f"Found {len(inputs)} inputs and {len(outputs)} outputs")

    def start_bridge(self) -> None:
        if self.runner is not None:
            return
        try:
            config = self._config()
        except ValueError as exc:
            QMessageBox.warning(self, "Configuration", str(exc))
            return

        self.start_button.setEnabled(False)
        self.stop_button.setEnabled(True)
        self.refresh_button.setEnabled(False)
        self.route_a.stop_meter()
        self.route_b.stop_meter()
        self._append_status("Starting")
        self.runner = BridgeRunner(
            config,
            on_status=self.signals.status.emit,
            on_transcript=self.signals.transcript.emit,
            on_error=self.signals.error.emit,
            on_stopped=self.signals.stopped.emit,
        )
        self.runner.start()

    def stop_bridge(self) -> None:
        if self.runner is not None:
            self._append_status("Stopping")
            self.runner.stop()
        self.stop_button.setEnabled(False)

    def _config(self) -> BridgeConfig:
        api_key = self.api_key.text().strip()
        if not api_key:
            raise ValueError("Enter an OpenAI API key or set OPENAI_API_KEY.")

        model = self.model.text().strip()
        if not model:
            raise ValueError("Enter a Realtime model name.")

        return BridgeConfig(
            api_key=api_key,
            model=model,
            route_a=self.route_a.config(),
            route_b=self.route_b.config(),
        )

    def _append_status(self, message: str) -> None:
        timestamp = datetime.now().strftime("%H:%M:%S")
        self.status_log.appendPlainText(f"[{timestamp}] {message}")

    def _append_transcript(self, route: str, kind: str, text: str, final: bool) -> None:
        self.transcripts.add_delta(route, kind, text, final)

    def _show_error(self, message: str) -> None:
        self._append_status(f"ERROR: {message}")
        QMessageBox.critical(self, "EchoPilot error", message)

    def _runner_stopped(self) -> None:
        self.runner = None
        self.start_button.setEnabled(True)
        self.stop_button.setEnabled(False)
        self.refresh_button.setEnabled(True)
        self.route_a.restart_meter()
        self.route_b.restart_meter()
        self._append_status("Stopped")

    def closeEvent(self, event) -> None:  # noqa: ANN001, N802
        if self.runner is not None:
            self.runner.stop()
        self.route_a.stop_meter()
        self.route_b.stop_meter()
        super().closeEvent(event)


if __name__ == "__main__":
    import sys
    from PySide6.QtWidgets import QApplication
    app = QApplication(sys.argv)
    win = MainWindow()
    win.show()
    sys.exit(app.exec())
