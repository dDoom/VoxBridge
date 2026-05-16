from __future__ import annotations

import asyncio
import base64
import inspect
import json
import re
import threading
import time
import traceback
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass
from urllib.parse import quote

import numpy as np
import websockets

from .audio import MicrophoneCapture, SpeakerLoopbackCapture
from .config import API_SAMPLE_RATE

DEFAULT_COPILOT_MODEL = "gpt-realtime-2"
DEFAULT_TRANSCRIPTION_MODEL = "gpt-realtime-whisper"
MAX_HINTS_PER_RESPONSE = 2
MIN_HINT_INTERVAL_SECONDS = 20.0
MIN_AUTO_ANALYSIS_INTERVAL_SECONDS = 45.0
URGENT_AUTO_ANALYSIS_INTERVAL_SECONDS = 15.0
MIN_LISTEN_BEFORE_FIRST_HINT_SECONDS = 25.0
MIN_NEW_TRANSCRIPT_CHARS = 120
MIN_NEW_TURNS = 2
MIN_NEW_AUDIO_TURNS = 2

StatusCallback = Callable[[str], None]
TranscriptCallback = Callable[[str], None]
HintCallback = Callable[[str, str], None]

ALLOWED_HINT_TYPES = {"argument", "fact", "action", "alert", "general"}
URGENT_HINT_RE = re.compile(
    r"\?|"
    r"\b(price|cost|budget|deadline|risk|issue|problem|concern|objection|contract|legal)\b|"
    r"(цен|стоим|бюджет|срок|дедлайн|риск|проблем|возраж|дорого|контракт|юрид)",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class CoPilotConfig:
    api_key: str
    input_device: int
    speaker_device: str | None = None
    meeting_goal: str = ""
    model: str = DEFAULT_COPILOT_MODEL
    transcription_model: str = DEFAULT_TRANSCRIPTION_MODEL
    context: str = ""


class CoPilotRealtimeClient:
    """Realtime audio listener that turns conversation transcripts into hint cards."""

    def __init__(
        self,
        config: CoPilotConfig,
        *,
        on_status: StatusCallback,
        on_transcript: TranscriptCallback,
        on_hint: HintCallback,
    ) -> None:
        self.config = config
        self.on_status = on_status
        self.on_transcript = on_transcript
        self.on_hint = on_hint
        self._turns: list[str] = []
        self._partials: dict[str, str] = {}
        self._hint_buffers: dict[str, str] = {}
        self._hint_in_flight = False
        self._hint_queued = False
        self._seen_hints: set[str] = set()
        self._event_counts: dict[str, int] = {}
        self._last_hint_emit_at = 0.0
        self._last_hint_request_at = 0.0
        self._last_hint_request_turn_index = 0
        self._audio_turn_count = 0
        self._last_hint_request_audio_turn_count = 0
        self._started_at = time.monotonic()
        self._request_lock: asyncio.Lock | None = None

    async def run(
        self,
        audio_frames: AsyncIterator[bytes],
        stop_event: asyncio.Event,
        suggest_event: asyncio.Event,
    ) -> None:
        self._request_lock = asyncio.Lock()
        model = quote(self.config.model, safe="")
        url = f"wss://api.openai.com/v1/realtime?model={model}"
        headers = {"Authorization": f"Bearer {self.config.api_key}"}

        async with self._connect(url, headers) as ws:
            self.on_status(
                f"Connected: model={self.config.model}, transcription={self.config.transcription_model}"
            )
            await self._configure_session(ws)

            sender = asyncio.create_task(self._send_audio(ws, audio_frames, stop_event))
            receiver = asyncio.create_task(self._receive_events(ws, stop_event))
            suggester = asyncio.create_task(
                self._watch_manual_suggestions(ws, suggest_event, stop_event)
            )
            auto_analyzer = asyncio.create_task(self._watch_auto_analysis(ws, stop_event))
            stopper = asyncio.create_task(stop_event.wait())

            done, pending = await asyncio.wait(
                {sender, receiver, suggester, auto_analyzer, stopper},
                return_when=asyncio.FIRST_COMPLETED,
            )
            stop_event.set()
            for task in pending:
                task.cancel()
            await asyncio.gather(*pending, return_exceptions=True)

            for task in done:
                if task is not stopper:
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
                "type": "realtime",
                "model": self.config.model,
                "output_modalities": ["text"],
                "audio": {
                    "input": {
                        "format": {"type": "audio/pcm", "rate": API_SAMPLE_RATE},
                        "transcription": {
                            "model": self.config.transcription_model,
                            "language": "ru",
                            "prompt": (
                                "The meeting is primarily in Russian. Keep Russian text in Cyrillic. "
                                "Preserve occasional English business terms, product names, and acronyms."
                            ),
                        },
                        "turn_detection": {
                            "type": "semantic_vad",
                            "create_response": False,
                            "interrupt_response": False,
                        },
                    }
                },
                "instructions": self._build_session_instructions(),
            },
        }
        await ws.send(json.dumps(event))

    async def _send_audio(
        self,
        ws,  # noqa: ANN001
        audio_frames: AsyncIterator[bytes],
        stop_event: asyncio.Event,
    ) -> None:
        sent_chunks = 0
        last_log_at = time.monotonic()
        async for chunk in audio_frames:
            if stop_event.is_set():
                return
            payload = base64.b64encode(chunk).decode("ascii")
            await ws.send(
                json.dumps({"type": "input_audio_buffer.append", "audio": payload})
            )
            sent_chunks += 1
            now = time.monotonic()
            if now - last_log_at >= 5.0:
                self.on_status(
                    f"Sent {sent_chunks} audio chunks ({sent_chunks * 0.02:.1f}s)"
                )
                last_log_at = now
            await asyncio.sleep(0)

    async def _receive_events(
        self,
        ws,  # noqa: ANN001
        stop_event: asyncio.Event,
    ) -> None:
        async for message in ws:
            if stop_event.is_set():
                return
            event = json.loads(message)
            self._log_event(event)
            await self._handle_event(event, ws)

    async def _handle_event(self, event: dict, ws) -> None:  # noqa: ANN001
        event_type = event.get("type", "")

        if event_type in {"session.created", "session.updated"}:
            self.on_status(event_type)
            return

        if event_type == "input_audio_buffer.speech_started":
            self.on_status("Speech detected")
            return

        if event_type == "input_audio_buffer.speech_stopped":
            self.on_status("Speech turn ended")
            return

        if event_type == "input_audio_buffer.committed":
            item_id = event.get("item_id") or ""
            self._audio_turn_count += 1
            self.on_status(f"Audio committed for transcription: {item_id}")
            return

        if event_type == "conversation.item.input_audio_transcription.delta":
            item_id = str(event.get("item_id") or "current")
            self._partials[item_id] = self._partials.get(item_id, "") + event.get("delta", "")
            self._emit_transcript_preview()
            return

        if event_type == "conversation.item.input_audio_transcription.completed":
            item_id = str(event.get("item_id") or "current")
            partial = self._partials.pop(item_id, "").strip()
            transcript = str(event.get("transcript") or "").strip()
            if partial and transcript and partial not in transcript and transcript not in partial:
                transcript = f"{partial} {transcript}".strip()
            elif not transcript:
                transcript = partial

            if transcript:
                self._turns.append(transcript)
                overflow = max(0, len(self._turns) - 14)
                if overflow:
                    self._turns = self._turns[overflow:]
                    self._last_hint_request_turn_index = max(
                        0,
                        self._last_hint_request_turn_index - overflow,
                    )
                self._emit_transcript_preview()
                await self._maybe_request_hint(ws, reason="auto")
            return

        if event_type == "conversation.item.input_audio_transcription.failed":
            error = event.get("error") or {}
            message = error.get("message") or error.get("code") or "Unknown transcription error"
            raise RuntimeError(f"Input transcription failed: {message}")

        if event_type == "response.created":
            response = event.get("response") or {}
            response_id = response.get("id")
            if response_id:
                self._hint_buffers[str(response_id)] = ""
                self.on_status("Generating hint")
            return

        if event_type == "response.output_text.delta":
            response_id = str(event.get("response_id") or "")
            if response_id in self._hint_buffers:
                self._hint_buffers[response_id] += str(event.get("delta") or "")
            return

        if event_type == "response.output_text.done":
            response_id = str(event.get("response_id") or "")
            text = str(event.get("text") or "")
            if response_id in self._hint_buffers and text:
                self._hint_buffers[response_id] = text
            return

        if event_type == "response.done":
            self._handle_response_done(event)
            return

        if event_type == "error":
            error = event.get("error", {})
            message = error.get("message", "Unknown Realtime API error")
            raise RuntimeError(message)

    def _log_event(self, event: dict) -> None:
        event_type = str(event.get("type") or "")
        if not event_type:
            return

        count = self._event_counts.get(event_type, 0) + 1
        self._event_counts[event_type] = count

        detail_parts: list[str] = []
        for key in ("item_id", "response_id", "previous_item_id"):
            value = event.get(key)
            if value:
                detail_parts.append(f"{key}={value}")

        if event_type in {
            "conversation.item.input_audio_transcription.delta",
            "conversation.item.input_audio_transcription.completed",
        }:
            text = str(event.get("delta") or event.get("transcript") or "")
            if text:
                detail_parts.append(f"text={text[:120]!r}")

        if event_type in {"error", "conversation.item.input_audio_transcription.failed"}:
            detail_parts.append(f"payload={json.dumps(event, ensure_ascii=False)[:500]}")

        details = f" {' '.join(detail_parts)}" if detail_parts else ""
        self.on_status(f"event[{count}] {event_type}{details}")

    def _handle_response_done(self, event: dict) -> None:
        response = event.get("response") or {}
        metadata = response.get("metadata") or {}
        force_response = str(metadata.get("force") or "").lower() == "true"
        response_id = str(response.get("id") or event.get("response_id") or "")
        raw_text = self._hint_buffers.pop(response_id, "") or self._response_text(response)
        hints = self._parse_hints(raw_text)
        if (
            hints
            and not force_response
            and time.monotonic() - self._last_hint_emit_at < MIN_HINT_INTERVAL_SECONDS
        ):
            remaining = MIN_HINT_INTERVAL_SECONDS - (time.monotonic() - self._last_hint_emit_at)
            self.on_status(f"Hints throttled; next card window in {remaining:.0f}s")
            self._hint_in_flight = False
            return

        emitted = 0
        for hint_type, text in hints[:MAX_HINTS_PER_RESPONSE]:
            key = self._dedupe_key(hint_type, text)
            if key in self._seen_hints:
                continue
            self._seen_hints.add(key)
            if len(self._seen_hints) > 80:
                self._seen_hints = set(list(self._seen_hints)[-40:])
            self.on_hint(hint_type, text)
            emitted += 1

        self._hint_in_flight = False
        if emitted:
            self._last_hint_emit_at = time.monotonic()
            self.on_status(f"Added {emitted} hint{'s' if emitted != 1 else ''}")
        else:
            self.on_status("No new hints")

    async def _watch_manual_suggestions(
        self,
        ws,  # noqa: ANN001
        suggest_event: asyncio.Event,
        stop_event: asyncio.Event,
    ) -> None:
        while not stop_event.is_set():
            await suggest_event.wait()
            suggest_event.clear()
            if stop_event.is_set():
                return
            await self._maybe_request_hint(ws, reason="manual", force=True)

    async def _watch_auto_analysis(
        self,
        ws,  # noqa: ANN001
        stop_event: asyncio.Event,
    ) -> None:
        while not stop_event.is_set():
            await asyncio.sleep(5.0)
            if stop_event.is_set():
                return
            if self._auto_analysis_window_ready():
                await self._maybe_request_hint(ws, reason="auto timer")

    async def _maybe_request_hint(
        self,
        ws,  # noqa: ANN001
        *,
        reason: str,
        force: bool = False,
    ) -> None:
        if self._request_lock is None:
            self._request_lock = asyncio.Lock()

        async with self._request_lock:
            await self._request_hint_locked(ws, reason=reason, force=force)

    async def _request_hint_locked(
        self,
        ws,  # noqa: ANN001
        *,
        reason: str,
        force: bool,
    ) -> None:
        if not self._turns and not self._audio_turn_count:
            if force and self._audio_turn_count:
                self.on_status("No transcript yet; asking from heard audio context")
            if force:
                self.on_status("No transcript yet for a hint")
            return
        if not self._turns and force:
            self.on_status("No transcript yet; asking from heard audio context")
        if self._hint_in_flight:
            self.on_status("Hint analysis already running")
            return

        should_request, request_reason = self._should_request_hint(force=force)
        if not should_request:
            return

        new_turns = self._new_turns_since_last_request()
        prompt = self._build_hint_prompt(request_reason or reason, new_turns)
        event = {
            "type": "response.create",
            "response": {
                "metadata": {
                    "kind": "echopilot_hint",
                    "reason": request_reason or reason,
                    "force": "true" if force else "false",
                },
                "output_modalities": ["text"],
                "max_output_tokens": 420,
                "instructions": prompt,
            },
        }
        self._hint_in_flight = True
        self._hint_queued = False
        self._last_hint_request_at = time.monotonic()
        self._last_hint_request_turn_index = len(self._turns)
        self._last_hint_request_audio_turn_count = self._audio_turn_count
        self.on_status(f"Analyzing conversation window: {request_reason or reason}")
        await ws.send(json.dumps(event))

    def _should_request_hint(self, *, force: bool) -> tuple[bool, str]:
        if force:
            return True, "manual request"

        now = time.monotonic()
        new_turns = self._new_turns_since_last_request()
        new_text = "\n".join(new_turns).strip()
        new_audio_turns = self._audio_turn_count - self._last_hint_request_audio_turn_count
        if not new_text and new_audio_turns <= 0:
            return False, ""

        since_start = now - self._started_at
        since_last = now - self._last_hint_request_at if self._last_hint_request_at else 999999.0
        has_urgent_signal = bool(URGENT_HINT_RE.search(new_text))
        if (
            has_urgent_signal
            and len(new_text) >= 40
            and since_last >= URGENT_AUTO_ANALYSIS_INTERVAL_SECONDS
        ):
            return True, "urgent signal"

        if since_start < MIN_LISTEN_BEFORE_FIRST_HINT_SECONDS:
            remaining = MIN_LISTEN_BEFORE_FIRST_HINT_SECONDS - since_start
            self.on_status(f"Listening first; first auto analysis in {remaining:.0f}s")
            return False, ""

        if since_last < MIN_AUTO_ANALYSIS_INTERVAL_SECONDS:
            remaining = MIN_AUTO_ANALYSIS_INTERVAL_SECONDS - since_last
            self.on_status(f"Listening; next auto analysis window in {remaining:.0f}s")
            return False, ""

        if len(new_text) >= MIN_NEW_TRANSCRIPT_CHARS:
            return True, f"{len(new_text)} new transcript chars"
        if len(new_turns) >= MIN_NEW_TURNS:
            return True, f"{len(new_turns)} new turns"
        if new_audio_turns >= MIN_NEW_AUDIO_TURNS:
            return True, f"{new_audio_turns} audio turns"

        self.on_status(
            f"Listening; need {MIN_NEW_TRANSCRIPT_CHARS - len(new_text)} more chars or "
            f"{MIN_NEW_TURNS - len(new_turns)} more text turns or "
            f"{MIN_NEW_AUDIO_TURNS - new_audio_turns} more audio turns"
        )
        return False, ""

    def _auto_analysis_window_ready(self) -> bool:
        if self._hint_in_flight or not self._turns:
            return False

        new_turns = self._new_turns_since_last_request()
        new_text = "\n".join(new_turns).strip()
        new_audio_turns = self._audio_turn_count - self._last_hint_request_audio_turn_count
        if not new_text and new_audio_turns <= 0:
            return False

        now = time.monotonic()
        since_last = now - self._last_hint_request_at if self._last_hint_request_at else 999999.0
        if (
            URGENT_HINT_RE.search(new_text)
            and len(new_text) >= 40
            and since_last >= URGENT_AUTO_ANALYSIS_INTERVAL_SECONDS
        ):
            return True

        if now - self._started_at < MIN_LISTEN_BEFORE_FIRST_HINT_SECONDS:
            return False
        if since_last < MIN_AUTO_ANALYSIS_INTERVAL_SECONDS:
            return False

        return (
            len(new_text) >= MIN_NEW_TRANSCRIPT_CHARS
            or len(new_turns) >= MIN_NEW_TURNS
            or new_audio_turns >= MIN_NEW_AUDIO_TURNS
        )

    def _new_turns_since_last_request(self) -> list[str]:
        index = max(0, min(self._last_hint_request_turn_index, len(self._turns)))
        return self._turns[index:]

    def _build_hint_prompt(self, reason: str, new_turns: list[str]) -> str:
        context = self._truncate(self.config.context.strip(), 9000)
        transcript = "\n".join(f"{index + 1}. {turn}" for index, turn in enumerate(self._turns[-10:]))
        new_transcript = "\n".join(
            f"{index + 1}. {turn}" for index, turn in enumerate(new_turns)
        )
        goal = self.config.meeting_goal.strip() or "No explicit meeting goal was provided."
        if not context:
            context = "No loaded context."
        if not new_transcript:
            new_transcript = "No new transcript since the last hint. Use the recent transcript."

        return (
            "You are listening to a live call and creating private on-screen hints.\n"
            "EchoPilot intentionally waited for a larger listening window before asking you.\n"
            "Use the actual audio conversation in this Realtime session as the primary source. "
            "Use the transcript below only as a rough aid because live transcription may contain errors.\n"
            "Hints should be rare, specific, short, and immediately usable. Prefer:\n"
            "- facts from the loaded context that answer or support the current topic;\n"
            "- suggested next questions or follow-up actions;\n"
            "- polite objections or arguments when the conversation needs them;\n"
            "- alerts only for risks, contradictions, deadlines, or missing information.\n\n"
            "Return only valid JSON with this exact schema:\n"
            '{"hints":[{"type":"argument|fact|action|alert|general","text":"short hint"}]}\n'
            "Do not summarize the whole conversation. Do not invent facts. Do not repeat old hints. "
            "Ignore previous assistant JSON hint outputs when deciding what the meeting participants said. "
            "Return one hint by default. Return two only if both are independent and important. "
            "If the transcript does not clearly call for help, return {\"hints\":[]}.\n\n"
            f"Analysis trigger: {reason}\n\n"
            f"Meeting goal:\n{goal}\n\n"
            f"Loaded context:\n{context}\n\n"
            f"New transcript since last analysis:\n{new_transcript}\n\n"
            f"Recent transcript:\n{transcript}\n"
        )

    def _build_session_instructions(self) -> str:
        context = self._truncate(self.config.context.strip(), 11000)
        goal = self.config.meeting_goal.strip() or "No explicit meeting goal was provided."
        if not context:
            context = "No loaded meeting materials."

        return (
            "You are EchoPilot, a private real-time meeting co-pilot. "
            "Listen to the whole conversation audio, including the user's microphone "
            "and meeting audio from speakers. Never speak to meeting participants. "
            "Return only text for the app UI.\n\n"
            "Your job is to produce short, useful hint cards based on the live discussion, "
            "the meeting goal, and the loaded materials. Use the materials as ground truth. "
            "Do not invent facts. Be selective: most short turns should return no hints. "
            "Only produce a hint when it is new, high-value, and immediately usable. "
            "If no useful hint is needed for the current turn, return "
            '{"hints":[]}.\n\n'
            "Always return valid JSON with this exact schema:\n"
            '{"hints":[{"type":"argument|fact|action|alert|general","text":"short hint"}]}\n'
            "Use at most two hints per response. Keep each hint under 220 characters.\n\n"
            f"Meeting goal:\n{goal}\n\n"
            f"Loaded materials:\n{context}\n"
        )

    def _emit_transcript_preview(self) -> None:
        lines = list(self._turns[-6:])
        for partial in self._partials.values():
            if partial.strip():
                lines.append(partial.strip())
        if lines:
            self.on_transcript("\n\n".join(lines[-6:]))

    @staticmethod
    def _response_text(response: dict) -> str:
        parts: list[str] = []
        for item in response.get("output") or []:
            for content in item.get("content") or []:
                text = content.get("text") or content.get("transcript")
                if text:
                    parts.append(str(text))
        return "\n".join(parts).strip()

    @staticmethod
    def _parse_hints(raw_text: str) -> list[tuple[str, str]]:
        text = raw_text.strip()
        if not text:
            return []

        fenced = re.search(r"```(?:json)?\s*(.*?)```", text, flags=re.DOTALL | re.IGNORECASE)
        if fenced:
            text = fenced.group(1).strip()

        if not text.startswith(("{", "[")):
            start = min((pos for pos in (text.find("{"), text.find("[")) if pos >= 0), default=-1)
            end = max(text.rfind("}"), text.rfind("]"))
            if start >= 0 and end > start:
                text = text[start : end + 1]

        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            if text.lower() in {"no hint", "no hints", "none"}:
                return []
            return [("general", CoPilotRealtimeClient._truncate(text, 280))]

        if isinstance(data, list):
            items = data
        elif isinstance(data, dict):
            items = data.get("hints") or []
        else:
            return []

        hints: list[tuple[str, str]] = []
        for item in items[:MAX_HINTS_PER_RESPONSE]:
            if not isinstance(item, dict):
                continue
            hint_type = str(item.get("type") or "general").lower().strip()
            if hint_type not in ALLOWED_HINT_TYPES:
                hint_type = "general"
            hint_text = str(item.get("text") or item.get("hint") or "").strip()
            if hint_text:
                hints.append((hint_type, CoPilotRealtimeClient._truncate(hint_text, 320)))
        return hints

    @staticmethod
    def _truncate(text: str, max_chars: int) -> str:
        if len(text) <= max_chars:
            return text
        return text[: max_chars - 16].rstrip() + "\n[...truncated]"

    @staticmethod
    def _dedupe_key(hint_type: str, text: str) -> str:
        normalized = re.sub(r"\W+", " ", text.lower()).strip()
        return f"{hint_type}:{normalized[:160]}"


class CoPilotRunner:
    def __init__(
        self,
        config: CoPilotConfig,
        *,
        on_status: StatusCallback,
        on_transcript: TranscriptCallback,
        on_hint: HintCallback,
        on_error: StatusCallback,
        on_stopped: Callable[[], None],
    ) -> None:
        self.config = config
        self.on_status = on_status
        self.on_transcript = on_transcript
        self.on_hint = on_hint
        self.on_error = on_error
        self.on_stopped = on_stopped
        self._thread: threading.Thread | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._stop_event: asyncio.Event | None = None
        self._suggest_event: asyncio.Event | None = None

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._thread = threading.Thread(target=self._thread_main, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        if self._loop and self._stop_event:
            self._loop.call_soon_threadsafe(self._stop_event.set)

    def request_hint(self) -> None:
        if self._loop and self._suggest_event:
            self._loop.call_soon_threadsafe(self._suggest_event.set)

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
        self._suggest_event = asyncio.Event()
        capture = CoPilotAudioCapture(self.config, self.on_status)
        client = CoPilotRealtimeClient(
            self.config,
            on_status=self.on_status,
            on_transcript=self.on_transcript,
            on_hint=self.on_hint,
        )

        capture.start()
        try:
            await client.run(capture.frames(), self._stop_event, self._suggest_event)
        finally:
            capture.close()
            self.on_status("Co-Pilot stopped")


class CoPilotAudioCapture:
    def __init__(self, config: CoPilotConfig, status: StatusCallback) -> None:
        self.config = config
        self.status = status
        self._captures: list[tuple[str, MicrophoneCapture | SpeakerLoopbackCapture]] = []

    def start(self) -> None:
        self._captures = [("microphone", MicrophoneCapture(self.config.input_device))]
        if self.config.speaker_device is not None:
            self._captures.append(
                ("meeting audio", SpeakerLoopbackCapture(self.config.speaker_device))
            )

        names = ", ".join(name for name, _ in self._captures)
        self.status(f"Starting {names}")
        try:
            for _, capture in self._captures:
                capture.start()
        except Exception:
            self.close()
            raise

    async def frames(self) -> AsyncIterator[bytes]:
        if not self._captures:
            raise RuntimeError("CoPilotAudioCapture.start() must be called first")

        queues = [asyncio.Queue(maxsize=8) for _ in self._captures]

        async def pump(
            capture: MicrophoneCapture | SpeakerLoopbackCapture,
            queue: asyncio.Queue[bytes],
        ) -> None:
            async for frame in capture.frames():
                if queue.full():
                    try:
                        queue.get_nowait()
                    except asyncio.QueueEmpty:
                        pass
                queue.put_nowait(frame)

        tasks = [
            asyncio.create_task(pump(capture, queue))
            for (_, capture), queue in zip(self._captures, queues, strict=True)
        ]
        try:
            while True:
                await asyncio.sleep(0.02)
                chunks = [self._latest_chunk(queue) for queue in queues]
                chunks = [chunk for chunk in chunks if chunk]
                if chunks:
                    yield self._mix_chunks(chunks)
        finally:
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)

    def close(self) -> None:
        for _, capture in self._captures:
            capture.close()
        self._captures = []

    @staticmethod
    def _latest_chunk(queue: asyncio.Queue[bytes]) -> bytes | None:
        chunk: bytes | None = None
        while True:
            try:
                chunk = queue.get_nowait()
            except asyncio.QueueEmpty:
                return chunk

    @staticmethod
    def _mix_chunks(chunks: list[bytes]) -> bytes:
        arrays = [np.frombuffer(chunk, dtype="<i2").astype(np.float32) for chunk in chunks]
        arrays = [array for array in arrays if array.size]
        if not arrays:
            return b""

        size = max(array.size for array in arrays)
        mixed = np.zeros(size, dtype=np.float32)
        for array in arrays:
            if array.size < size:
                padded = np.zeros(size, dtype=np.float32)
                padded[: array.size] = array
                array = padded
            mixed += array[:size]

        mixed /= max(1, len(arrays))
        return np.clip(mixed, -32768, 32767).astype("<i2").tobytes()
