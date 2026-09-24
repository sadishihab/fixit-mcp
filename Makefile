.PHONY: run test lint format inspector tunnel fetch-manuals parse-manuals extract-codes \
	docker-build docker-run docker-smoke

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

# Extracts structured error-code records from data/manuals/parsed/*.json into
# data/index/error_codes.json (committed). Defaults to FIXIT_EXTRACTOR=stub
# (no AWS needed); set FIXIT_EXTRACTOR=bedrock to use Amazon Bedrock instead.
# Pass MANUAL=<manual_id> to process just one manual, FORCE=1 to bypass the
# per-chunk cache.
extract-codes:
	uv run python scripts/extract_codes.py $(if $(MANUAL),--manual $(MANUAL),) $(if $(FORCE),--force,)

# --- Container (AgentCore Runtime target: linux/arm64) -----------------------
# See README's "Running in Docker" section. On an x86_64 host, arm64 builds and
# runs need QEMU binfmt handlers registered once per boot:
#   docker run --privileged --rm tonistiigi/binfmt --install arm64
DOCKER_IMAGE ?= fixit-mcp:latest
DOCKER_PLATFORM ?= linux/arm64
# Named volume for the SQLite store, so local household data survives
# `docker rm`. This is a local-testing convenience only -- AgentCore Runtime
# has no equivalent shared volume by default (see FRICTION_LOG.md, step 4a).
DOCKER_STATE_VOLUME ?= fixit-mcp-state

docker-build:
	docker buildx build --platform $(DOCKER_PLATFORM) -t $(DOCKER_IMAGE) --load .

docker-run:
	docker run --rm --name fixit-mcp --platform $(DOCKER_PLATFORM) -p 8000:8000 \
		-v $(DOCKER_STATE_VOLUME):/app/data/state $(DOCKER_IMAGE)

# Runs scripts/smoke_test.py against a server already listening on
# localhost:8000 (e.g. `make docker-run` in another terminal). Skips the p95
# latency check automatically when the image's platform differs from the
# host's (QEMU emulation, ~10x slower than native -- it would measure QEMU,
# not the server).
DOCKER_HOST_ARCH := $(shell uname -m | sed -e 's/x86_64/amd64/' -e 's/aarch64/arm64/')
docker-smoke:
	uv run python scripts/smoke_test.py --url http://localhost:8000/mcp --wait 90 \
		$(if $(filter linux/$(DOCKER_HOST_ARCH),$(DOCKER_PLATFORM)),,--skip-latency)
