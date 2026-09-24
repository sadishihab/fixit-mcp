from pathlib import Path
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_SQLITE_PATH = REPO_ROOT / "data" / "state" / "appliances.db"


class Settings(BaseSettings):
    """Runtime configuration, overridable via FIXIT_* environment variables or a .env file."""

    model_config = SettingsConfigDict(env_prefix="FIXIT_", env_file=".env", extra="ignore")

    host: str = "0.0.0.0"
    port: int = 8000
    streamable_http_path: str = "/mcp"
    log_level: str = "INFO"
    # Plain JSON responses (instead of SSE) since our tools are fast, non-streaming
    # lookups with no server-initiated messages to push.
    json_response: bool = True
    # "sqlite" persists appliances across restarts (data/state/, gitignored) --
    # the default, so the demo works out of the box. "memory" is for tests and
    # for anyone who wants a clean slate every run. "agentcore" stores them in
    # Amazon Bedrock AgentCore Memory -- the only backend whose data is shared
    # across AgentCore Runtime sessions (each session is its own microVM, see
    # FRICTION_LOG.md step 4a). Needs agentcore_memory_id and AWS credentials.
    repository_backend: Literal["memory", "sqlite", "agentcore"] = "sqlite"
    sqlite_path: Path = DEFAULT_SQLITE_PATH
    # The memory resource's id (not its ARN or name), e.g. "FixItHouseholds-a1B2c3D4e5".
    agentcore_memory_id: str = ""
    agentcore_region: str = "us-east-1"
    # The one fixed AgentCore Memory sessionId each household's appliance
    # events live under (actorId = household_id).
    agentcore_registry_session_id: str = "appliance-registry"
