"""One shared normalization for appliance types (step 16b).

Customers (and the assistant) say "washer", "washing machine" or "clothes
washer"; the seed data stores "washing_machine". Matching used to be exact, so
`check_warranty(appliance_type="washer")` told a customer with a registered
washer that they had none (FRICTION_LOG.md, step 16a eval). Every place that
compares or stores a type goes through `normalize_appliance_type`:
check_warranty compares normalize(stored) with normalize(query), and
add_appliance stores the normalized form. Values already stored are never
rewritten; they still match because both sides are normalized at compare time.
"""

from __future__ import annotations

import re

# canonical type -> the phrasings that mean it. Canonical names are the ones the
# seed data already uses (fixit_mcp.repository.in_memory.DEFAULT_SEED).
_SYNONYMS: dict[str, tuple[str, ...]] = {
    "washing_machine": ("washer", "washing machine", "washing_machine", "clothes washer", "laundry machine"),
    "dryer": ("dryer", "clothes dryer", "tumble dryer"),
    "refrigerator": ("refrigerator", "fridge", "freezer", "fridge freezer"),
    "dishwasher": ("dishwasher", "dish washer"),
    # The seed data calls the GE JBP26 a "range"; an oven or stove is the same
    # appliance to a customer asking about its warranty.
    "range": ("range", "oven", "stove", "cooker", "wall oven"),
}


def _key(text: str) -> str:
    return re.sub(r"[\s_-]+", " ", text.strip().lower())


_LOOKUP: dict[str, str] = {_key(s): canonical for canonical, syns in _SYNONYMS.items() for s in syns}


def normalize_appliance_type(appliance_type: str) -> str:
    """The canonical type for a known synonym; otherwise the input lowercased with
    spaces/hyphens as underscores, so an unknown type still compares consistently
    (and never silently matches a different appliance)."""
    key = _key(appliance_type)
    return _LOOKUP.get(key, key.replace(" ", "_"))


def appliance_types_match(a: str, b: str) -> bool:
    return normalize_appliance_type(a) == normalize_appliance_type(b)
