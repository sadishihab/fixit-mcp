.PHONY: run test lint format inspector tunnel fetch-manuals parse-manuals

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

# Downloads manuals listed in data/manuals/manifest.yaml to data/manuals/pdf/.
# Pass FORCE=1 to re-download files that already exist.
fetch-manuals:
	uv run python scripts/fetch_manuals.py $(if $(FORCE),--force,)

# Parses every PDF in data/manuals/pdf/ into section-aware chunks, written to
# data/manuals/parsed/<manual_id>.json. Run `make fetch-manuals` first.
parse-manuals:
	uv run python scripts/parse_manuals.py
