"""FastAPI backend for a simulated Alexa+ conversation with FixIt.

This is NOT the real Alexa+ client -- it's a local stand-in that plays the
same role (an MCP client driving a tool-use LLM loop against this server)
so the tool-calling and MCP Apps card behavior can be exercised and demoed
before a real Alexa+ integration exists. Every response is labeled
"simulated Alexa+" so it's never mistaken for the real thing.

Bound to 127.0.0.1 only (see demo/__main__.py); CORS limited to localhost.
AWS credentials -- Bedrock, and SigV4 for a deployed FixIt runtime -- stay
server-side: never returned to the caller or logged.
"""

from __future__ import annotations

import time
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import boto3
import structlog
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse
from mcp import ClientSession
from pydantic import BaseModel

from demo.config import DemoSettings
from demo.mcp_session import MCPTarget, SessionManager, ToolDef, discover_tool_defs
from demo.orchestrator import ConversationStore, build_system_prompt, is_transient_transport_error, run_turn
from demo.web import INDEX_HTML

# Any localhost origin, any port -- this demo has no web UI of its own yet
# (step 6a), but a future one served from a dev server on some local port
# still needs to be able to call it.
_LOCALHOST_ORIGIN_REGEX = r"^http://(localhost|127\.0\.0\.1)(:\d+)?$"


class ChatRequest(BaseModel):
    message: str
    session_id: str


class ToolCallOut(BaseModel):
    name: str
    arguments: dict[str, Any]
    result: dict[str, Any] | None
    latency_ms: float


class CardOut(BaseModel):
    resource_uri: str
    html: str


class ChatResponse(BaseModel):
    reply_text: str
    tool_calls: list[ToolCallOut]
    card: CardOut | None = None
    simulated_alexa_plus: bool = True


def create_app(target: MCPTarget, settings: DemoSettings | None = None) -> FastAPI:
    settings = settings or DemoSettings()
    sessions = SessionManager(target)
    conversations = ConversationStore()
    bedrock = boto3.client("bedrock-runtime", region_name=settings.bedrock_region)
    system_prompt = build_system_prompt(settings.household_id)
    state: dict[str, list[ToolDef]] = {}

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        # tools/list once at startup, not per request or per conversation --
        # the model's tool definitions come from what the server actually
        # advertises right now, never a hardcoded list.
        state["tool_defs"] = await discover_tool_defs(target)
        try:
            yield
        finally:
            await sessions.aclose()

    app = FastAPI(
        title="FixIt simulated Alexa+ demo",
        description="A local stand-in for Alexa+'s MCP client, for demoing FixIt. Not the real Alexa+.",
        lifespan=lifespan,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origin_regex=_LOCALHOST_ORIGIN_REGEX,
        allow_methods=["GET", "POST"],
        allow_headers=["*"],
    )

    @app.get("/", response_class=HTMLResponse)
    async def root() -> str:
        # The single-page simulated-Alexa+ UI (demo/static/index.html),
        # loaded once at import time -- see demo/web.py.
        return INDEX_HTML

    @app.post("/chat", response_model=ChatResponse)
    async def chat(request: ChatRequest) -> ChatResponse | JSONResponse:
        logger = structlog.get_logger()
        turn_id = uuid.uuid4().hex[:12]
        total_start = time.perf_counter()

        # A session_id not seen before means the next line pays for a
        # brand-new MCP session -- against a deployed AgentCore Runtime,
        # that's a cold session (FRICTION_LOG.md's cold-start entries).
        # Timed and logged separately from the Bedrock/tool-use loop below
        # so the two costs are never conflated when reading the logs.
        session_was_cold = not sessions.is_open(request.session_id)
        operation = "session_setup"

        try:
            session_start = time.perf_counter()
            session = await sessions.get(request.session_id)
            session_setup_ms = (time.perf_counter() - session_start) * 1000

            history = conversations.get(request.session_id)

            def converse(**kwargs: Any) -> dict[str, Any]:
                return bedrock.converse(**kwargs)

            async def refresh_session() -> ClientSession:
                # Only called after a "session terminated" failure proves
                # the current session is permanently stale (see
                # orchestrator._call_tool_with_retry) -- evict() discards it
                # even though its background task never itself crashed, and
                # get() opens a genuinely fresh one (a fresh initialize(),
                # a fresh Mcp-Session-Id) for the rest of this conversation.
                await sessions.evict(request.session_id)
                return await sessions.get(request.session_id)

            operation = "run_turn"
            turn_start = time.perf_counter()
            result = await run_turn(
                converse=converse,
                model_id=settings.bedrock_model_id,
                system_prompt=system_prompt,
                messages=history,
                tool_defs=state["tool_defs"],
                session=session,
                user_message=request.message,
                max_rounds=settings.max_tool_rounds,
                refresh_session=refresh_session,
            )
            turn_ms = (time.perf_counter() - turn_start) * 1000
        except Exception as exc:
            # Whatever failed, get a record of it before anything else --
            # this is the one place a failing turn produces any signal at
            # all; previously nothing logged a failure (see FRICTION_LOG.md).
            # The specific tool in flight, if any, is attached by
            # orchestrator._call_tool_with_retry as exc.fixit_operation;
            # never invented, only reported when the code that raised it
            # actually knows. Never logs request/response bodies, headers,
            # or credentials -- only the exception's own type and message.
            retryable = is_transient_transport_error(exc)
            logger.warning(
                "demo_chat_turn_failed",
                session_id=request.session_id,
                turn_id=turn_id,
                operation=getattr(exc, "fixit_operation", operation),
                exception_type=type(exc).__name__,
                exception_message=str(exc),
                retryable=retryable,
                session_was_cold=session_was_cold,
                elapsed_ms=round((time.perf_counter() - total_start) * 1000, 1),
            )
            if retryable:
                return JSONResponse(
                    status_code=502, content={"error": "runtime_transport_error", "retryable": True}
                )
            return JSONResponse(status_code=500, content={"error": "internal_error", "retryable": False})

        logger.info(
            "demo_chat_turn",
            session_id=request.session_id,
            turn_id=turn_id,
            session_was_cold=session_was_cold,
            session_setup_ms=round(session_setup_ms, 1),
            turn_ms=round(turn_ms, 1),
            tool_call_ms=round(sum(tc.latency_ms for tc in result.tool_calls), 1),
            tool_call_count=len(result.tool_calls),
            retried_tool_calls=sum(1 for tc in result.tool_calls if tc.retried),
            input_tokens=result.input_tokens,
            output_tokens=result.output_tokens,
            total_ms=round((time.perf_counter() - total_start) * 1000, 1),
        )

        return ChatResponse(
            reply_text=result.reply_text,
            tool_calls=[
                ToolCallOut(name=tc.name, arguments=tc.arguments, result=tc.result, latency_ms=tc.latency_ms)
                for tc in result.tool_calls
            ],
            card=CardOut(resource_uri=result.card.resource_uri, html=result.card.html)
            if result.card
            else None,
        )

    return app
