"""demo.app: the FastAPI wiring itself -- GET / serves the web UI page, and
/chat's route is unchanged by that addition. No AWS, no real MCP server:
`create_app` only touches the network inside request handlers (`/chat`)
and the FastAPI lifespan (`tools/list` at startup), neither of which these
tests exercise, so a placeholder MCPTarget that's never dereferenced is
enough.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from demo.app import create_app
from demo.config import DemoSettings
from demo.mcp_session import MCPTarget
from demo.web import INDEX_HTML


def _client() -> TestClient:
    target = MCPTarget(url="http://localhost:1/mcp", auth=None)
    app = create_app(target, DemoSettings())
    return TestClient(app)


def test_root_serves_the_web_ui_page() -> None:
    response = _client().get("/")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert response.text == INDEX_HTML
    assert "Simulated Alexa+" in response.text


def test_root_page_is_not_the_old_json_stub() -> None:
    # The old GET / returned {"service": "fixit-demo", ...} JSON. Confirm
    # that shape is gone and an HTML document is served instead.
    response = _client().get("/")

    assert response.text.strip().lower().startswith("<!doctype html>")


def test_chat_route_is_unchanged() -> None:
    app = _client().app
    chat_routes = [route for route in app.routes if getattr(route, "path", None) == "/chat"]

    assert len(chat_routes) == 1
    route = chat_routes[0]
    assert route.methods == {"POST"}
    assert route.response_model.__name__ == "ChatResponse"
