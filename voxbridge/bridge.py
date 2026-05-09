from __future__ import annotations

import asyncio
import threading
import traceback
from collections.abc import Callable

from .audio import MicrophoneCapture, SpeakerOutput
from .config import BridgeConfig, RouteConfig
from .realtime import RealtimeTranslator

StatusCallback = Callable[[str], None]
TranscriptCallback = Callable[[str, str, str, bool], None]


class TranslationRoute:
    def __init__(
        self,
        route: RouteConfig,
        *,
        api_key: str,
        model: str,
        status: StatusCallback,
        transcript: TranscriptCallback,
    ) -> None:
        self.route = route
        self.status = status
        self.capture = MicrophoneCapture(route.input_device)
        self.output = SpeakerOutput(route.output_device)
        self.translator = RealtimeTranslator(
            api_key=api_key,
            model=model,
            source_language=route.source_language,
            target_language=route.target_language,
            status=lambda msg: status(f"{route.name}: {msg}"),
            transcript=lambda kind, text, final: transcript(route.name, kind, text, final),
        )

    async def run(self, stop_event: asyncio.Event) -> None:
        self.status(f"{self.route.name}: starting audio devices")
        self.capture.start()
        self.output.start()
        try:
            await self.translator.run(
                self.capture.frames(),
                self.output.play_api_audio,
                stop_event,
            )
        finally:
            self.capture.close()
            self.output.close()
            self.status(f"{self.route.name}: stopped")


class BridgeRunner:
    def __init__(
        self,
        config: BridgeConfig,
        *,
        on_status: StatusCallback,
        on_transcript: TranscriptCallback,
        on_error: StatusCallback,
        on_stopped: Callable[[], None],
    ) -> None:
        self.config = config
        self.on_status = on_status
        self.on_transcript = on_transcript
        self.on_error = on_error
        self.on_stopped = on_stopped
        self._thread: threading.Thread | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._stop_event: asyncio.Event | None = None

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._thread = threading.Thread(target=self._thread_main, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        if self._loop and self._stop_event:
            self._loop.call_soon_threadsafe(self._stop_event.set)

    def _thread_main(self) -> None:
        try:
            asyncio.run(self._run())
        except Exception as exc:  # noqa: BLE001
            self.on_error(f"{exc}\n{traceback.format_exc(limit=4)}")
        finally:
            self.on_stopped()

    async def _run(self) -> None:
        self._loop = asyncio.get_running_loop()
        self._stop_event = asyncio.Event()
        routes = [
            route
            for route in (self.config.route_a, self.config.route_b)
            if route.enabled
        ]
        if not routes:
            raise RuntimeError("Enable at least one translation route.")

        tasks = [
            asyncio.create_task(
                TranslationRoute(
                    route,
                    api_key=self.config.api_key,
                    model=self.config.model,
                    status=self.on_status,
                    transcript=self.on_transcript,
                ).run(self._stop_event)
            )
            for route in routes
        ]

        stopper = asyncio.create_task(self._stop_event.wait())
        done, pending = await asyncio.wait(
            [*tasks, stopper],
            return_when=asyncio.FIRST_COMPLETED,
        )

        self._stop_event.set()
        for task in pending:
            task.cancel()
        await asyncio.gather(*pending, return_exceptions=True)

        for task in done:
            if task is not stopper:
                task.result()
