"""scripts/try_it.py against the real dev server: the walkthrough the README's
no-AWS quickstart promises has to keep matching what the server returns."""

import importlib.util
import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"
spec = importlib.util.spec_from_file_location("fixit_try_it_integration", SCRIPTS / "try_it.py")
try_it = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = try_it
spec.loader.exec_module(try_it)


async def test_walkthrough_against_the_dev_server(server_url: str) -> None:
    sections: list[str] = []

    async def body(session) -> None:
        sections.extend(await try_it.walkthrough(session))

    await try_it._with_session(server_url, body)
    text = "\n".join(sections)

    assert "tool error" not in text
    assert "LG DLEX8000W (dryer), registered to this household" in text
    assert "status: expired" in text
    assert "LG WM4000HWA (washing_machine), NOT registered to this household" in text
    assert "status: not_found" in text
    assert "source: LG DLEX8000W manual, page 31" in text
