# FixIt MCP server -- AgentCore Runtime container (linux/arm64).
#
# AgentCore's MCP container contract (docs.aws.amazon.com/bedrock-agentcore,
# "MCP protocol contract"): listen on 0.0.0.0:8000, serve Streamable HTTP at
# /mcp, ARM64 image. The server already does all three by default
# (fixit_mcp.config.Settings + stateless_http=True in server.py), so nothing
# here overrides host/port/path.
#
# Two stages: the builder has uv and resolves the locked, prod-only
# dependency set; the runtime stage is plain python:3.12-slim with just the
# virtualenv, the source, and the two data files the server loads at startup.

# The target platform comes from the build command (`make docker-build`
# passes --platform linux/arm64), not a hardcoded FROM --platform, per
# buildx's FromPlatformFlagConstDisallowed check.
ARG PYTHON_IMAGE=python:3.12-slim-bookworm

# uv is pinned to the same version that wrote uv.lock (see pyproject.toml's
# uv_build pin); copied in as a static binary so both stages share one base.
FROM ghcr.io/astral-sh/uv:0.12.18 AS uv

FROM ${PYTHON_IMAGE} AS builder
COPY --from=uv /uv /bin/uv

# Compile bytecode once at build time (faster cold start in a fresh microVM),
# copy rather than hardlink out of the uv cache mount, and use the base
# image's own /usr/local/bin/python3 so the venv's interpreter symlink stays
# valid in the runtime stage, which is built from that same base image.
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=0 \
    UV_PYTHON=/usr/local/bin/python3

WORKDIR /app

# Dependencies first, in their own layer, so source-only changes don't
# re-resolve/re-download anything. --no-dev drops boto3/pymupdf/pytest/etc.
# (offline ingestion + test tooling, never imported by the running server).
RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    uv sync --frozen --no-dev --no-install-project

# Then the project itself. Deliberately an *editable* install (uv's default):
# config.py, catalog/manifest.py and retrieval/codes.py locate data/ via
# Path(__file__).parents[N], which only resolves to /app/data when the
# package runs from /app/src -- a non-editable install into site-packages
# would point them at .venv/lib/..., see FRICTION_LOG.md (step 4a).
COPY pyproject.toml uv.lock README.md ./
COPY src ./src
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev


FROM ${PYTHON_IMAGE} AS runtime

# UID 1000, matching the non-root user the AgentCore CLI's own generated
# images use (bedrock_agentcore, UID 1000) -- and the UID an EFS/S3 Files
# access point would need to be configured with, if one is ever mounted.
RUN groupadd --system --gid 1000 fixit \
    && useradd --system --uid 1000 --gid fixit --no-create-home --home-dir /app fixit

WORKDIR /app

COPY --from=builder --chown=fixit:fixit /app/.venv ./.venv
COPY --from=builder --chown=fixit:fixit /app/src ./src
# Only the two committed data files the running server reads at startup --
# not manual PDFs, parsed chunks, the extraction cache, or local state.
COPY --chown=fixit:fixit data/index/error_codes.json ./data/index/error_codes.json
COPY --chown=fixit:fixit data/manuals/manifest.yaml ./data/manuals/manifest.yaml

# The SQLite store's directory must exist and be owned by the app user so a
# named volume mounted here inherits that ownership. NOTE: in AgentCore
# Runtime this path is microVM-local and ephemeral -- see README's Docker
# section and FRICTION_LOG.md (step 4a) before relying on it there.
RUN mkdir -p /app/data/state && chown fixit:fixit /app/data/state

ENV PATH="/app/.venv/bin:${PATH}" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

USER fixit

EXPOSE 8000

CMD ["python", "-m", "fixit_mcp"]
