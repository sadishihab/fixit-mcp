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

APPS_DIR = Path(__file__).resolve().parent

DIAGNOSE_CARD_RESOURCE_URI = "ui://fixit-mcp/diagnose-error-card"
DIAGNOSE_CARD_PATH = APPS_DIR / "diagnose_card.html"
DIAGNOSE_CARD_NAME = "fixit-mcp-diagnose-card"

SYMPTOM_CARD_RESOURCE_URI = "ui://fixit-mcp/diagnose-symptom-card"
SYMPTOM_CARD_PATH = APPS_DIR / "symptom_card.html"
SYMPTOM_CARD_NAME = "fixit-mcp-diagnose-symptom-card"

# The pieces both cards share, in one place (step 27a). A card template marks where each goes with a
# line holding only its marker; `assemble_card` swaps them in. The CSS head/tail are the contiguous
# runs the two cards have in common (the root colour variables, body and card chrome, the citation,
# the muted state styles), the JS is the escape helper, and the handshake is the MCP Apps postMessage
# exchange, so both cards speak it identically.
_SHARED_PARTS = {
    "@@SHARED_CSS_HEAD@@\n": "card_shared_head.css",
    "@@SHARED_CSS_TAIL@@\n": "card_shared_tail.css",
    "@@SHARED_JS@@\n": "card_shared.js",
    "@@SHARED_HANDSHAKE@@\n": "card_handshake.js",
}


def assemble_card(template_path: Path, card_name: str) -> str:
    """A card's complete, self-contained HTML document: its template with the shared CSS, escape
    helper and handshake filled in. Runs once at import time; the result is a plain string."""
    html = template_path.read_text()
    for marker, filename in _SHARED_PARTS.items():
        html = html.replace(marker, (APPS_DIR / filename).read_text())
    return html.replace("@@CARD_NAME@@", card_name)


DIAGNOSE_CARD_HTML = assemble_card(DIAGNOSE_CARD_PATH, DIAGNOSE_CARD_NAME)
SYMPTOM_CARD_HTML = assemble_card(SYMPTOM_CARD_PATH, SYMPTOM_CARD_NAME)
