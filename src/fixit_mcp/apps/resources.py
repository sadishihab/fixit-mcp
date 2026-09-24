"""MCP Apps UI resources for FixIt's tools.

Per the current MCP Apps spec (modelcontextprotocol/ext-apps,
specification/2026-01-26/apps.mdx): a tool links to its UI via
`_meta.ui.resourceUri` declared on the *tool definition* (static, one shared
template per tool, visible in `tools/list`) -- not per call result, which the
spec doesn't define UI metadata for at all. The template itself must be a
self-contained HTML5 document served at a `ui://` URI with MIME type
`text/html;profile=mcp-app`, fetched via a normal `resources/read`. The
template's own small JS (not this server) receives that call's actual result
data via a postMessage-based handshake with the host and decides what to
render -- see diagnose_card.html's inline comments and FRICTION_LOG.md for
why a purely static, pre-rendered-per-call resource isn't how any current
host is built to look for one.

Loaded once at import time (module-level constant), never read from disk
per-request, per CLAUDE.md rule 3/4.
"""

from pathlib import Path

DIAGNOSE_CARD_RESOURCE_URI = "ui://fixit-mcp/diagnose-error-card"
DIAGNOSE_CARD_PATH = Path(__file__).resolve().parent / "diagnose_card.html"
DIAGNOSE_CARD_HTML = DIAGNOSE_CARD_PATH.read_text()
