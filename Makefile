.PHONY: run test lint format inspector tunnel

run:
	uv run python -m fixit_mcp

test:
	uv run pytest -v

lint:
	uv run ruff check .

format:
	uv run ruff format .

# Requires Node.js/npm. Point the Inspector's UI at http://localhost:8000/mcp
# with transport "Streamable HTTP" once it opens in your browser.
inspector:
	npx @modelcontextprotocol/inspector

# Requires cloudflared (see README's Quickstart section for install instructions).
# Exposes the local server at http://localhost:8000 via a temporary HTTPS URL,
# which is what Alexa+'s MCP Toolkit needs since it requires a remote HTTPS endpoint.
tunnel:
	cloudflared tunnel --url http://localhost:8000
