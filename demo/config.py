"""Config for the simulated-Alexa+ demo backend (demo/).

Kept separate from fixit_mcp.config.Settings (the running MCP server) and
fixit_mcp.ingestion.extraction.ExtractionSettings (offline ingestion tooling)
-- this is a third, independent client application. Neither the server nor
ingestion imports this, and this never imports them beyond what the demo's
own MCP client needs (CLAUDE.md).
"""

from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class DemoSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="FIXIT_DEMO_", env_file=".env", extra="ignore")

    host: str = "127.0.0.1"
    port: int = 8090

    # No web UI yet (step 6a), so there's no per-customer login to derive
    # this from -- every simulated conversation serves this one seeded
    # household until a real front end can supply its own.
    household_id: str = "house-002"

    # Fresh-household mode (step 14), OFF by default so behavior is unchanged:
    # when on, every new conversation (every new session_id, which is what the
    # page's "New conversation" makes) gets its own throwaway `house-demo-<random>`
    # household, seeded on its first turn with the same LG dryer and GE washer
    # as house-002. `household_id` above is then unused. `make demo-cleanup`
    # removes the households listed in `households_file`.
    fresh_household: bool = False
    households_file: str = "data/state/demo_households.txt"

    # Same defaults as fixit_mcp.ingestion.extraction.ExtractionSettings --
    # see there for why this exact dated/cross-region model id, not a bare
    # or undated one (verified working in this project's dev AWS account).
    bedrock_region: str = "us-east-1"
    bedrock_model_id: str = "us.anthropic.claude-sonnet-4-5-20250929-v1:0"

    # Caps the Converse tool-use loop so a misbehaving model can't spin
    # forever calling tools without ever producing a final answer.
    max_tool_rounds: int = 4

    # Time budgets, so one dropped response can never hang a turn (FRICTION_LOG.md,
    # step 13): each MCP tool call / resource read, each Bedrock Converse call,
    # and the whole turn (which bounds the sum of several rounds).
    tool_timeout_seconds: float = 15.0
    converse_timeout_seconds: float = 30.0
    turn_timeout_seconds: float = 90.0

    # Only read by the opt-in live test (FIXIT_DEMO_TESTS=1) -- a deployed
    # AgentCore Runtime ARN to run one real conversation against.
    live_agent_arn: str = ""

    # Spoken replies through Amazon Polly (step 24b), OFF by default: the page
    # then keeps using the browser's own voice. When on, POST /speak
    # synthesizes with the generative engine; the browser never sees AWS
    # credentials, only audio bytes.
    polly: bool = False
    polly_region: str = "us-east-1"
    polly_engine: str = "generative"
    polly_voice: str = "Matthew"
    # Longest text one /speak call accepts. Replies are one or two sentences.
    polly_request_max_chars: int = 500
    # Spend guard: characters synthesized by this process. Past this, /speak
    # answers 503 and the page falls back to the browser voice. Cache hits
    # are free and never count. Restarting the process resets the count.
    polly_max_chars: int = 50_000
    polly_timeout_seconds: float = 5.0
    # Audio is cached here by hash of engine, voice, format and text.
    polly_cache_dir: str = "demo/.audio_cache"
