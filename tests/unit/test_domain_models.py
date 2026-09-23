import pytest

from fixit_mcp.domain.models import normalize_code


@pytest.mark.parametrize(
    ("typed", "expected"),
    [
        ("E24", "E24"),
        ("E-24", "E24"),
        ("E:24-00", "E2400"),
        ("e 24", "E24"),
        ("tE1", "TE1"),
        ("TE1", "TE1"),
    ],
)
def test_normalize_code_handles_how_people_actually_type_it(typed: str, expected: str) -> None:
    assert normalize_code(typed) == expected


def test_normalize_code_is_idempotent() -> None:
    once = normalize_code("E:24-00")
    twice = normalize_code(once)
    assert once == twice == "E2400"
