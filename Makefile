.PHONY: run test lint format inspector tunnel fetch-manuals parse-manuals extract-codes \
	docker-build docker-run docker-smoke docker-run-agentcore seed-agentcore \
	iam-policies docker-push deploy-runtime runtime-smoke runtime-latency teardown-runtime teardown-runtime-all

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

# The image on the "agentcore" backend, i.e. how it will run on AgentCore
# Runtime: household data in real AgentCore Memory, nothing on local disk.
# Local-only credential passing (host ~/.aws, read-only); on AgentCore
# Runtime the execution role supplies credentials instead.
docker-run-agentcore:
	@test -n "$(FIXIT_AGENTCORE_MEMORY_ID)" || (echo "set FIXIT_AGENTCORE_MEMORY_ID" && exit 1)
	docker run --rm --name fixit-mcp --platform $(DOCKER_PLATFORM) -p 8000:8000 \
		-v $(HOME)/.aws:/aws:ro -e AWS_CONFIG_FILE=/aws/config -e AWS_SHARED_CREDENTIALS_FILE=/aws/credentials \
		-e FIXIT_REPOSITORY_BACKEND=agentcore -e FIXIT_AGENTCORE_MEMORY_ID=$(FIXIT_AGENTCORE_MEMORY_ID) \
		$(DOCKER_IMAGE)

# Runs scripts/smoke_test.py against a server already listening on
# localhost:8000 (e.g. `make docker-run` in another terminal). Skips the p95
# latency check automatically when the image's platform differs from the
# host's (QEMU emulation, ~10x slower than native -- it would measure QEMU,
# not the server).
DOCKER_HOST_ARCH := $(shell uname -m | sed -e 's/x86_64/amd64/' -e 's/aarch64/arm64/')
docker-smoke:
	uv run python scripts/smoke_test.py --url http://localhost:8000/mcp --wait 90 \
		$(if $(filter linux/$(DOCKER_HOST_ARCH),$(DOCKER_PLATFORM)),,--skip-latency)

# --- AgentCore Memory (household appliances, "agentcore" backend) ------------
# Idempotently puts the demo households (house-001/002) into the memory
# resource named by FIXIT_AGENTCORE_MEMORY_ID. The backend never seeds at
# runtime (see FRICTION_LOG.md, step 4b). RESET=1 first clears everything in
# the demo households (e.g. appliances added while rehearsing a demo).
seed-agentcore:
	uv run python scripts/seed_agentcore_memory.py $(if $(RESET),--reset,)

# --- AgentCore Runtime deployment (step 4c, direct path: ECR + CreateAgentRuntime) ---
# See README's "Deploying to AgentCore Runtime" section. All of these need AWS
# credentials; deploy/runtime targets also need FIXIT_AGENTCORE_MEMORY_ID.
# RUNTIME_ARN is printed by `make deploy-runtime`.

# Fill deploy/iam/*.json templates with this account's values -> build/iam/.
iam-policies:
	uv run python scripts/render_iam_policies.py

# Push the already-built, already-tested local image (make docker-build) to
# ECR. No rebuild -- this is the "deploy exactly what was tested" step.
docker-push:
	uv run python scripts/push_image.py --local-image $(DOCKER_IMAGE)

# Create or update the runtime, pinned to the pushed image's digest. Idempotent.
deploy-runtime:
	uv run python scripts/deploy_runtime.py

runtime-smoke:
	@test -n "$(RUNTIME_ARN)" || (echo "set RUNTIME_ARN (printed by make deploy-runtime)" && exit 1)
	uv run python scripts/smoke_test.py --agent-arn $(RUNTIME_ARN) --wait 5

runtime-latency:
	@test -n "$(RUNTIME_ARN)" || (echo "set RUNTIME_ARN (printed by make deploy-runtime)" && exit 1)
	uv run python scripts/measure_runtime_latency.py --agent-arn $(RUNTIME_ARN)

# STOP PAYING: deletes the runtime (all sessions, the endpoint, all compute
# charges). Keeps the ECR image (~$0.01/month) and AgentCore Memory data.
teardown-runtime:
	uv run python scripts/deploy_runtime.py --delete

# Same, plus the ECR repository and every image in it. Still keeps the
# AgentCore Memory resource (household data) and the IAM roles/policies.
teardown-runtime-all:
	uv run python scripts/deploy_runtime.py --delete --delete-image-repo
