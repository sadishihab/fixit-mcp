"""demo/speech.py and POST /speak (step 24b): cache hit and miss, disabled,
failure, the per-request cap, the spend guard, and that nothing here needs AWS.
A fake Polly client stands in for boto3; no network."""

from __future__ import annotations

import io
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from demo.app import create_app
from demo.config import DemoSettings
from demo.mcp_session import MCPTarget
from demo.speech import Speaker, SpeechUnavailable

AUDIO = b"ID3-fake-mp3-bytes"


class FakePollyClient:
    def __init__(self, audio: bytes = AUDIO, error: Exception | None = None, delay: float = 0.0) -> None:
        self.audio = audio
        self.error = error
        self.delay = delay
        self.calls: list[dict[str, Any]] = []

    def synthesize_speech(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(kwargs)
        if self.delay:
            import time

            time.sleep(self.delay)
        if self.error:
            raise self.error
        return {"AudioStream": io.BytesIO(self.audio), "ContentType": "audio/mpeg"}


def settings(tmp_path: Path, **overrides: Any) -> DemoSettings:
    values: dict[str, Any] = {"polly": True, "polly_cache_dir": str(tmp_path / "cache")}
    values.update(overrides)
    return DemoSettings(**values)


def client_for(tmp_path: Path, fake: FakePollyClient | None, **overrides: Any) -> TestClient:
    target = MCPTarget(url="http://localhost:1/mcp", auth=None)
    return TestClient(create_app(target, settings(tmp_path, **overrides), polly_client=fake))


# --- defaults ---------------------------------------------------------------


def test_polly_is_off_by_default() -> None:
    s = DemoSettings(_env_file=None)
    assert s.polly is False
    assert (s.polly_engine, s.polly_voice) == ("generative", "Matthew")
    assert s.polly_request_max_chars == 500
    assert s.polly_max_chars == 50_000


def test_env_var_switches_polly_on_and_sets_the_budget(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FIXIT_DEMO_POLLY", "1")
    monkeypatch.setenv("FIXIT_DEMO_POLLY_MAX_CHARS", "1234")
    s = DemoSettings(_env_file=None)
    assert s.polly is True
    assert s.polly_max_chars == 1234


# --- /speak -----------------------------------------------------------------


def test_disabled_returns_503_and_never_calls_polly(tmp_path: Path) -> None:
    fake = FakePollyClient()
    client = client_for(tmp_path, fake, polly=False)

    response = client.post("/speak", json={"text": "Hello."})

    assert response.status_code == 503
    assert response.json() == {"error": "speech_disabled"}
    assert fake.calls == []


def test_disabled_does_not_create_a_boto3_client(tmp_path: Path) -> None:
    # No injected client and polly off: constructing must not touch boto3/AWS.
    target = MCPTarget(url="http://localhost:1/mcp", auth=None)
    app = create_app(target, settings(tmp_path, polly=False))
    assert TestClient(app).post("/speak", json={"text": "Hi"}).status_code == 503


def test_miss_calls_polly_with_the_configured_engine_and_voice(tmp_path: Path) -> None:
    fake = FakePollyClient()
    client = client_for(tmp_path, fake)

    response = client.post("/speak", json={"text": "  Your dryer shows tE1.  "})

    assert response.status_code == 200
    assert response.headers["content-type"] == "audio/mpeg"
    assert response.headers["x-speech-cache"] == "miss"
    assert response.content == AUDIO
    assert fake.calls == [
        {
            "Engine": "generative",
            "VoiceId": "Matthew",
            "OutputFormat": "mp3",
            "Text": "Your dryer shows tE1.",
            "TextType": "text",
        }
    ]


def test_second_identical_request_is_a_cache_hit_and_costs_nothing(tmp_path: Path) -> None:
    fake = FakePollyClient()
    client = client_for(tmp_path, fake)

    first = client.post("/speak", json={"text": "Same words."})
    second = client.post("/speak", json={"text": "Same words."})

    assert first.content == second.content == AUDIO
    assert second.headers["x-speech-cache"] == "hit"
    assert len(fake.calls) == 1


def test_cache_survives_a_new_process(tmp_path: Path) -> None:
    first = client_for(tmp_path, FakePollyClient())
    first.post("/speak", json={"text": "Persisted."})

    fake = FakePollyClient()
    second = client_for(tmp_path, fake)
    response = second.post("/speak", json={"text": "Persisted."})

    assert response.headers["x-speech-cache"] == "hit"
    assert fake.calls == []


def test_different_voice_or_text_is_a_different_cache_entry(tmp_path: Path) -> None:
    fake = FakePollyClient()
    client_for(tmp_path, fake).post("/speak", json={"text": "One."})
    client_for(tmp_path, fake, polly_voice="Joanna").post("/speak", json={"text": "One."})
    client_for(tmp_path, fake).post("/speak", json={"text": "Two."})

    assert len(fake.calls) == 3


def test_polly_failure_is_503_and_nothing_is_cached(tmp_path: Path) -> None:
    failing = client_for(tmp_path, FakePollyClient(error=RuntimeError("boom")))

    response = failing.post("/speak", json={"text": "Hello."})

    assert response.status_code == 503
    assert response.json() == {"error": "speech_failed"}
    cache = tmp_path / "cache"
    assert not cache.exists() or not list(cache.iterdir())
    # A later success is not poisoned by the failure.
    ok = client_for(tmp_path, FakePollyClient()).post("/speak", json={"text": "Hello."})
    assert ok.status_code == 200 and ok.headers["x-speech-cache"] == "miss"


def test_empty_audio_is_a_failure(tmp_path: Path) -> None:
    response = client_for(tmp_path, FakePollyClient(audio=b"")).post("/speak", json={"text": "Hi."})
    assert response.status_code == 503


def test_slow_polly_times_out_as_503(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("demo.speech._GUARD_MARGIN_S", 0.0)
    fake = FakePollyClient(delay=0.6)
    client = client_for(tmp_path, fake, polly_timeout_seconds=0.05)

    assert client.post("/speak", json={"text": "Slow."}).status_code == 503


def test_text_over_the_cap_is_rejected_without_calling_polly(tmp_path: Path) -> None:
    fake = FakePollyClient()
    client = client_for(tmp_path, fake)

    exactly = client.post("/speak", json={"text": "a" * 500})
    over = client.post("/speak", json={"text": "a" * 501})

    assert exactly.status_code == 200
    assert over.status_code == 413
    assert over.json() == {"error": "text_too_long"}
    assert len(fake.calls) == 1


def test_blank_text_is_rejected(tmp_path: Path) -> None:
    fake = FakePollyClient()
    response = client_for(tmp_path, fake).post("/speak", json={"text": "   "})

    assert response.status_code == 422
    assert fake.calls == []


# --- spend guard -------------------------------------------------------------


def test_budget_hard_stop_counts_only_synthesized_characters(tmp_path: Path) -> None:
    fake = FakePollyClient()
    client = client_for(tmp_path, fake, polly_max_chars=20)

    assert client.post("/speak", json={"text": "a" * 10}).status_code == 200  # 10 used
    assert client.post("/speak", json={"text": "a" * 10}).headers["x-speech-cache"] == "hit"  # free
    assert client.post("/speak", json={"text": "b" * 10}).status_code == 200  # 20 used
    stopped = client.post("/speak", json={"text": "c"})

    assert stopped.status_code == 503
    assert stopped.json() == {"error": "speech_budget_exhausted"}
    assert len(fake.calls) == 2
    # Already-cached audio is still served after the budget is spent.
    assert client.post("/speak", json={"text": "a" * 10}).status_code == 200


@pytest.mark.asyncio
async def test_failed_synthesis_refunds_its_characters(tmp_path: Path) -> None:
    speaker = Speaker(settings(tmp_path), FakePollyClient(error=RuntimeError("boom")))

    with pytest.raises(SpeechUnavailable):
        await speaker.speak("Hello.")

    assert speaker.chars_synthesized == 0


@pytest.mark.asyncio
async def test_counter_tracks_successful_characters(tmp_path: Path) -> None:
    speaker = Speaker(settings(tmp_path), FakePollyClient())

    await speaker.speak("Hello.")  # 6
    await speaker.speak("Hello.")  # cached
    await speaker.speak("Hi there.")  # 9

    assert speaker.chars_synthesized == 15


def test_default_budget_stops_at_fifty_thousand(tmp_path: Path) -> None:
    speaker = Speaker(settings(tmp_path), FakePollyClient())
    speaker.chars_synthesized = 49_999

    with pytest.raises(SpeechUnavailable) as info:
        import asyncio

        asyncio.run(speaker.speak("ab"))

    assert info.value.code == "speech_budget_exhausted"


def test_budget_env_override_is_honored(tmp_path: Path) -> None:
    assert settings(tmp_path, polly_max_chars=100_000).polly_max_chars == 100_000


# --- credentials never reach the page ----------------------------------------


def test_speak_response_carries_no_credentials(tmp_path: Path) -> None:
    response = client_for(tmp_path, FakePollyClient()).post("/speak", json={"text": "Hi."})

    blob = (str(response.headers) + response.content.decode("latin-1")).lower()
    assert "akia" not in blob and "secret" not in blob and "token" not in blob
