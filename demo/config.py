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

    # Same defaults as fixit_mcp.ingestion.extraction.ExtractionSettings --
    # see there for why this exact dated/cross-region model id, not a bare
    # or undated one (verified working in this project's dev AWS account).
    bedrock_region: str = "us-east-1"
    bedrock_model_id: str = "us.anthropic.claude-sonnet-4-5-20250929-v1:0"

    # Caps the Converse tool-use loop so a misbehaving model can't spin
    # forever calling tools without ever producing a final answer.
    max_tool_rounds: int = 4

    # Only read by the opt-in live test (FIXIT_DEMO_TESTS=1) -- a deployed
    # AgentCore Runtime ARN to run one real conversation against.
    live_agent_arn: str = ""
