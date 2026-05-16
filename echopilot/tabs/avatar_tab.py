"""Avatar tab — virtual camera with lip-sync delay."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSlider,
    QVBoxLayout,
    QWidget,
)


class AvatarTab(QWidget):
    """Controls for virtual camera output with frame delay."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._setup_ui()

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setSpacing(16)
        layout.setContentsMargins(16, 16, 16, 16)

        # Toggle
        self._toggle = QPushButton("📷 Enable Virtual Camera")
        self._toggle.setCheckable(True)
        self._toggle.setStyleSheet(
            "QPushButton { background:#22c55e; color:#000; border:none; border-radius:6px; "
            "padding:10px 20px; font-weight:600; font-size:14px; }"
            "QPushButton:checked { background:#ef4444; }"
        )
        layout.addWidget(self._toggle)

        # Preview
        preview = QGroupBox("Webcam Preview")
        p_layout = QVBoxLayout(preview)
        self._preview = QLabel("Camera preview will appear here")
        self._preview.setMinimumHeight(200)
        self._preview.setStyleSheet(
            "QLabel { background:#0a0a0f; border:1px solid #1e1e2d; border-radius:8px; "
            "color:#94a3b8; font-size:12px; }"
        )
        self._preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        p_layout.addWidget(self._preview)
        layout.addWidget(preview)

        # Settings
        settings = QGroupBox("Settings")
        s_layout = QVBoxLayout(settings)

        # Camera selector
        cam_row = QHBoxLayout()
        cam_row.addWidget(QLabel("Real camera:"))
        self._cam_select = QComboBox()
        self._cam_select.setMinimumWidth(200)
        cam_row.addWidget(self._cam_select)
        cam_row.addStretch()
        s_layout.addLayout(cam_row)

        # Delay
        delay_row = QHBoxLayout()
        delay_row.addWidget(QLabel("Delay:"))
        self._delay_slider = QSlider(Qt.Orientation.Horizontal)
        self._delay_slider.setRange(0, 2000)
        self._delay_slider.setValue(500)
        delay_row.addWidget(self._delay_slider)
        self._delay_label = QLabel("500 ms")
        delay_row.addWidget(self._delay_label)
        s_layout.addLayout(delay_row)

        # Resolution
        res_row = QHBoxLayout()
        res_row.addWidget(QLabel("Resolution:"))
        self._res_select = QComboBox()
        self._res_select.addItems(["480p", "720p", "1080p"])
        res_row.addWidget(self._res_select)
        res_row.addStretch()
        s_layout.addLayout(res_row)

        # FPS
        fps_row = QHBoxLayout()
        fps_row.addWidget(QLabel("FPS limit:"))
        self._fps_select = QComboBox()
        self._fps_select.addItems(["15", "30", "60"])
        fps_row.addWidget(self._fps_select)
        fps_row.addStretch()
        s_layout.addLayout(fps_row)

        layout.addWidget(settings)

        # Metrics
        metrics = QGroupBox("Metrics")
        m_layout = QHBoxLayout(metrics)
        self._latency_label = QLabel("Latency: --")
        self._latency_label.setStyleSheet("color:#94a3b8;")
        m_layout.addWidget(self._latency_label)
        self._status_label = QLabel("Status: Idle")
        self._status_label.setStyleSheet("color:#94a3b8;")
        m_layout.addWidget(self._status_label)
        m_layout.addStretch()
        layout.addWidget(metrics)

        layout.addStretch()

        # Signals
        self._delay_slider.valueChanged.connect(self._update_delay_label)

    def _update_delay_label(self, value: int) -> None:
        self._delay_label.setText(f"{value} ms")
