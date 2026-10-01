"""Spoken replies for the simulated-Alexa+ demo, through Amazon Polly (step 24b).

Demo-only, OFF by default (`FIXIT_DEMO_POLLY=0`). The running MCP server never
imports this. The browser asks `POST /speak` for audio of a reply it already
shows; AWS credentials stay in this process and only MP3 bytes go back.

Cost controls, because every synthesized character is billed:
- a cache keyed by a hash of engine, voice, format and text, so a repeated
  reply costs nothing (cache hits never count toward the guard);
- a per-request character cap;
- a per-process character budget with a hard stop (`polly_max_chars`).
Every failure is a `SpeechUnavailable`; the page then uses the browser voice.
"""

from __future__ import annotations

import asyncio
import hashlib
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import structlog

from demo.config import DemoSettings
from demo.orchestrator import within

# Slack on top of the boto3 read timeout, so botocore normally fails first.
_GUARD_MARGIN_S = 1.0
OUTPUT_FORMAT = "mp3"
MEDIA_TYPE = "audio/mpeg"


class SpeechUnavailable(Exception):
    """/speak cannot return audio. `code` is the machine-readable reason."""

    def __init__(self, code: str, status_code: int = 503) -> None:
        super().__init__(code)
        self.code = code
        self.status_code = status_code


@dataclass
class Speech:
    audio: bytes
    cache_hit: bool


class Speaker:
    def __init__(self, settings: DemoSettings, client: Any | None = None) -> None:
        self._enabled = settings.polly
        self._engine = settings.polly_engine
        self._voice = settings.polly_voice
        self._request_max = settings.polly_request_max_chars
        self._budget = settings.polly_max_chars
        self._timeout = settings.polly_timeout_seconds
        self._cache_dir = Path(settings.polly_cache_dir)
        self._client = client
        if self._enabled and self._client is None:
            import boto3
            from botocore.config import Config

            # Tight limits and one attempt: a slow Polly must not hold up the page,
            # which falls back to the browser voice.
            self._client = boto3.client(
                "polly",
                region_name=settings.polly_region,
                config=Config(
                    connect_timeout=2,
                    read_timeout=settings.polly_timeout_seconds,
                    retries={"max_attempts": 1},
                ),
            )
        self.chars_synthesized = 0

    @property
    def enabled(self) -> bool:
        return self._enabled

    def _cache_path(self, text: str) -> Path:
        key = f"{self._engine}|{self._voice}|{OUTPUT_FORMAT}|{text}".encode()
        return self._cache_dir / f"{hashlib.sha256(key).hexdigest()}.{OUTPUT_FORMAT}"

    def _synthesize(self, text: str) -> bytes:
        response = self._client.synthesize_speech(
            Engine=self._engine,
            VoiceId=self._voice,
            OutputFormat=OUTPUT_FORMAT,
            Text=text,
            TextType="text",
        )
        return response["AudioStream"].read()

    async def speak(self, text: str) -> Speech:
        logger = structlog.get_logger()
        if not self._enabled:
            raise SpeechUnavailable("speech_disabled")
        text = text.strip()
        if not text:
            raise SpeechUnavailable("empty_text", 422)
        if len(text) > self._request_max:
            raise SpeechUnavailable("text_too_long", 413)

        path = self._cache_path(text)
        try:
            cached = path.read_bytes()
        except OSError:
            cached = None
        if cached:
            logger.info("demo_speak", chars=len(text), cache_hit=True, latency_ms=0.0)
            return Speech(cached, cache_hit=True)

        if self.chars_synthesized + len(text) > self._budget:
            logger.warning(
                "demo_speak_budget_exhausted",
                chars=len(text),
                chars_synthesized_total=self.chars_synthesized,
                budget=self._budget,
            )
            raise SpeechUnavailable("speech_budget_exhausted")

        # Reserve before the call so concurrent requests cannot overshoot; refund
        # on failure, since a failed synthesis is not billed.
        self.chars_synthesized += len(text)
        start = time.perf_counter()
        try:
            audio = await within(
                self._timeout + _GUARD_MARGIN_S, "polly", asyncio.to_thread(self._synthesize, text)
            )
            if not audio:
                raise ValueError("Polly returned no audio")
        except Exception as exc:
            self.chars_synthesized -= len(text)
            logger.warning(
                "demo_speak_failed",
                chars=len(text),
                exception_type=type(exc).__name__,
                exception_message=str(exc),
                latency_ms=round((time.perf_counter() - start) * 1000, 1),
            )
            raise SpeechUnavailable("speech_failed") from exc

        latency_ms = round((time.perf_counter() - start) * 1000, 1)
        try:
            self._cache_dir.mkdir(parents=True, exist_ok=True)
            tmp = path.with_suffix(".tmp")
            tmp.write_bytes(audio)
            tmp.replace(path)
        except OSError as exc:
            logger.warning("demo_speak_cache_write_failed", exception_type=type(exc).__name__)
        logger.info(
            "demo_speak",
            chars=len(text),
            cache_hit=False,
            latency_ms=latency_ms,
            chars_synthesized_total=self.chars_synthesized,
            budget=self._budget,
        )
        return Speech(audio, cache_hit=False)
