from __future__ import annotations

import asyncio
import base64
import inspect
import json
from collections.abc import AsyncIterator, Awaitable, Callable

import websockets

from .config import API_SAMPLE_RATE

StatusCallback = Callable[[str], None]
AudioCallback = Callable[[bytes], Awaitable[None]]
TranscriptCallback = Callable[[str, str, bool], None]


class RealtimeTranslator:
    def __init__(
        self,
        *,
        api_key: str,
        model: str,
        source_language: str,
        target_language: str,
        status: StatusCallback,
        transcript: TranscriptCallback,
    ) -> None:
        self.api_key = api_key
        self.model = model
        self.source_language = source_language
        self.target_language = target_language
        self.status = status
        self.transcript = transcript

    async def run(
        self,
        audio_frames: AsyncIterator[bytes],
        on_audio: AudioCallback,
        stop_event: asyncio.Event,
    ) -> None:
        url = f"wss://api.openai.com/v1/realtime/translations?model={self.model}"
        headers = {"Authorization": f"Bearer {self.api_key}"}

        async with self._connect(url, headers) as ws:
            self.status("Connected to OpenAI Realtime")
            await self._configure_session(ws)

            sender = asyncio.create_task(self._send_audio(ws, audio_frames, stop_event))
            receiver = asyncio.create_task(self._receive_events(ws, on_audio, stop_event))

            done, pending = await asyncio.wait(
                {sender, receiver},
                return_when=asyncio.FIRST_EXCEPTION,
            )
            for task in pending:
                task.cancel()
            for task in done:
                task.result()

    @staticmethod
    def _connect(url: str, headers: dict[str, str]):
        parameters = inspect.signature(websockets.connect).parameters
        if "additional_headers" in parameters:
            return websockets.connect(url, additional_headers=headers, max_size=None)
        return websockets.connect(url, extra_headers=headers, max_size=None)

    async def _configure_session(self, ws) -> None:  # noqa: ANN001
        event = {
            "type": "session.update",
            "session": {
                "audio": {
                    "input": {
                        "transcription": {"model": "gpt-realtime-whisper"},
                        "noise_reduction": {"type": "near_field"},
                    },
                    "output": {
                        "language": self.target_language,
                    },
                },
            },
        }
        await ws.send(json.dumps(event))

    async def _send_audio(
        self,
        ws,  # noqa: ANN001
        audio_frames: AsyncIterator[bytes],
        stop_event: asyncio.Event,
    ) -> None:
        async for chunk in audio_frames:
            if stop_event.is_set():
                return
            payload = base64.b64encode(chunk).decode("ascii")
            await ws.send(
                json.dumps({"type": "session.input_audio_buffer.append", "audio": payload})
            )
            await asyncio.sleep(0)

    async def _receive_events(
        self,
        ws,  # noqa: ANN001
        on_audio: AudioCallback,
        stop_event: asyncio.Event,
    ) -> None:
        async for message in ws:
            if stop_event.is_set():
                return

            event = json.loads(message)
            event_type = event.get("type", "")

            if event_type in {"session.created", "session.updated"}:
                self.status(event_type)
            elif event_type in {
                "session.output_audio.delta",
                "response.output_audio.delta",
                "response.audio.delta",
            }:
                delta = event.get("delta")
                if delta:
                    await on_audio(base64.b64decode(delta))
            elif event_type in {
                "session.output_transcript.delta",
                "session.input_transcript.delta",
            }:
                delta = event.get("delta")
                if delta:
                    kind = "translation" if "output" in event_type else "source"
                    self.transcript(kind, delta, False)
            elif event_type in {
                "session.output_transcript.done",
                "session.input_transcript.done",
            }:
                text = event.get("transcript") or event.get("text") or event.get("delta") or ""
                kind = "translation" if "output" in event_type else "source"
                self.transcript(kind, text, True)
            elif event_type == "error":
                error = event.get("error", {})
                message = error.get("message", "Unknown Realtime API error")
                raise RuntimeError(message)
