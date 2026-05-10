from __future__ import annotations

import asyncio
import threading
from collections import deque
from dataclasses import dataclass
from typing import AsyncIterator

import numpy as np
import sounddevice as sd

from .config import API_SAMPLE_RATE


@dataclass(frozen=True)
class AudioDevice:
    index: int
    name: str
    hostapi: str
    max_input_channels: int
    max_output_channels: int
    default_samplerate: int

    @property
    def label(self) -> str:
        return f"{self.index}: {self.name} ({self.hostapi}, {self.default_samplerate} Hz)"


def list_audio_devices() -> list[AudioDevice]:
    hostapis = sd.query_hostapis()
    devices = sd.query_devices()
    result: list[AudioDevice] = []
    for index, device in enumerate(devices):
        hostapi = hostapis[device["hostapi"]]["name"]
        result.append(
            AudioDevice(
                index=index,
                name=str(device["name"]),
                hostapi=str(hostapi),
                max_input_channels=int(device["max_input_channels"]),
                max_output_channels=int(device["max_output_channels"]),
                default_samplerate=int(device["default_samplerate"]),
            )
        )
    return result


def default_sample_rate(device_index: int) -> int:
    device = sd.query_devices(device_index)
    return int(device["default_samplerate"])


def resample_pcm16_mono(data: bytes, source_rate: int, target_rate: int) -> bytes:
    if not data or source_rate == target_rate:
        return data

    samples = np.frombuffer(data, dtype="<i2")
    if samples.size == 0:
        return data

    duration = samples.size / float(source_rate)
    target_size = max(1, int(round(duration * target_rate)))
    old_positions = np.linspace(0.0, 1.0, samples.size, endpoint=False)
    new_positions = np.linspace(0.0, 1.0, target_size, endpoint=False)
    resampled = np.interp(new_positions, old_positions, samples).astype("<i2")
    return resampled.tobytes()


class MicrophoneCapture:
    def __init__(self, device_index: int, sample_rate: int | None = None) -> None:
        self.device_index = device_index
        self.sample_rate = sample_rate or default_sample_rate(device_index)
        self._queue: asyncio.Queue[bytes] | None = None
        self._stream: sd.RawInputStream | None = None

    def start(self) -> None:
        loop = asyncio.get_running_loop()
        self._queue = asyncio.Queue(maxsize=80)

        def callback(indata, frames, time, status) -> None:  # noqa: ANN001, ARG001
            chunk = bytes(indata)

            def put_chunk() -> None:
                if self._queue is None:
                    return
                if self._queue.full():
                    try:
                        self._queue.get_nowait()
                    except asyncio.QueueEmpty:
                        pass
                self._queue.put_nowait(chunk)

            loop.call_soon_threadsafe(put_chunk)

        blocksize = max(240, int(self.sample_rate * 0.02))
        self._stream = sd.RawInputStream(
            samplerate=self.sample_rate,
            blocksize=blocksize,
            device=self.device_index,
            channels=1,
            dtype="int16",
            callback=callback,
        )
        self._stream.start()

    async def frames(self) -> AsyncIterator[bytes]:
        if self._queue is None:
            raise RuntimeError("MicrophoneCapture.start() must be called first")
        while True:
            chunk = await self._queue.get()
            yield resample_pcm16_mono(chunk, self.sample_rate, API_SAMPLE_RATE)

    def close(self) -> None:
        if self._stream is not None:
            self._stream.stop()
            self._stream.close()
            self._stream = None
        self._queue = None


class SpeakerOutput:
    def __init__(self, device_index: int, sample_rate: int | None = None) -> None:
        self.device_index = device_index
        self.sample_rate = sample_rate or default_sample_rate(device_index)
        self._stream: sd.RawOutputStream | None = None
        self._translated: deque[np.ndarray] = deque()
        self._original: deque[np.ndarray] = deque()
        self._lock = threading.Lock()
        self._max_buffer_samples = self.sample_rate * 3

    def start(self) -> None:
        blocksize = max(240, int(self.sample_rate * 0.02))
        self._stream = sd.RawOutputStream(
            samplerate=self.sample_rate,
            blocksize=blocksize,
            device=self.device_index,
            channels=1,
            dtype="int16",
            callback=self._callback,
        )
        self._stream.start()

    async def play_api_audio(self, data: bytes) -> None:
        if self._stream is None:
            raise RuntimeError("SpeakerOutput.start() must be called first")
        self._queue_audio(self._translated, data, 1.0)

    async def play_original_audio(self, data: bytes, volume_percent: int) -> None:
        if self._stream is None:
            raise RuntimeError("SpeakerOutput.start() must be called first")
        gain = max(0.0, min(float(volume_percent), 100.0)) / 100.0
        if gain <= 0.0:
            return
        self._queue_audio(self._original, data, gain)

    def close(self) -> None:
        if self._stream is not None:
            self._stream.stop()
            self._stream.close()
            self._stream = None
        with self._lock:
            self._translated.clear()
            self._original.clear()

    def _queue_audio(self, buffer: deque[np.ndarray], data: bytes, gain: float) -> None:
        converted = resample_pcm16_mono(data, API_SAMPLE_RATE, self.sample_rate)
        samples = np.frombuffer(converted, dtype="<i2").astype(np.float32)
        if samples.size == 0:
            return
        samples *= gain
        with self._lock:
            buffer.append(samples)
            self._trim_buffer(buffer)

    def _callback(self, outdata, frames, time, status) -> None:  # noqa: ANN001, ARG002
        mixed = np.zeros(frames, dtype=np.float32)
        with self._lock:
            mixed += self._read_buffer(self._original, frames)
            mixed += self._read_buffer(self._translated, frames)
        clipped = np.clip(mixed, -32768, 32767).astype("<i2")
        outdata[:] = clipped.tobytes()

    def _trim_buffer(self, buffer: deque[np.ndarray]) -> None:
        buffered = sum(chunk.size for chunk in buffer)
        while buffered > self._max_buffer_samples and buffer:
            removed = buffer.popleft()
            buffered -= removed.size

    @staticmethod
    def _read_buffer(buffer: deque[np.ndarray], frames: int) -> np.ndarray:
        output = np.zeros(frames, dtype=np.float32)
        offset = 0
        while offset < frames and buffer:
            chunk = buffer[0]
            take = min(frames - offset, chunk.size)
            output[offset : offset + take] = chunk[:take]
            offset += take
            if take == chunk.size:
                buffer.popleft()
            else:
                buffer[0] = chunk[take:]
        return output
