from pydantic_settings import BaseSettings, SettingsConfigDict


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
