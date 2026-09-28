"""Loads the demo's single static web page (demo/static/index.html).

Mirrors fixit_mcp/apps/resources.py's pattern: loaded once at import time,
never read from disk per request.
"""

from pathlib import Path

INDEX_HTML_PATH = Path(__file__).resolve().parent / "static" / "index.html"
INDEX_HTML = INDEX_HTML_PATH.read_text()
