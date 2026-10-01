"""Synthetic symptom data for the matcher/tool tests: invented appliances and invented strings, no
manual text. Two manuals (a washer and a refrigerator) share one symptom on purpose."""

from __future__ import annotations

from fixit_mcp.domain.models import Appliance, SymptomRecord
from fixit_mcp.repository.in_memory import InMemoryApplianceRepository
from fixit_mcp.retrieval.symptoms import SymptomIndex, build_index

WASHER = "acme-w100-washer"
FRIDGE = "bravo-r200-fridge"


def rec(
    manual: str,
    symptom: list[str],
    causes: list[str],
    actions: list[str],
    *,
    continued: bool = False,
    label: str = "Problem",
    response: str = "What To Do",
    footnotes: list[str] | None = None,
    incomplete: bool = False,
    page: int = 5,
) -> SymptomRecord:
    washer = manual == WASHER
    return SymptomRecord(
        manual_id=manual,
        brand="Acme" if washer else "Bravo",
        model="W100" if washer else "R200",
        appliance_type="washing_machine" if washer else "refrigerator",
        symptom=symptom,
        symptom_label=label,
        symptom_continued=continued,
        possible_causes=causes,
        what_to_do=actions,
        response_label=response,
        footnotes=footnotes or [],
        text_incomplete=incomplete,
        source_page=page,
        source_section="Troubleshooting Tips",
    )


def synthetic_records() -> list[SymptomRecord]:
    return [
        rec(WASHER, ["Drum stays still"], ["Hatch not latched"], ["Close the hatch firmly."]),
        rec(WASHER, ["Drum stays still"], ["Plug is loose"], ["Push the plug in."], continued=True),
        rec(
            WASHER,
            ["Tub overflows onto the floor", "Water pours out"],
            ["Too much soap"],
            ["Use a smaller scoop."],
            footnotes=["*Select models only"],
            page=6,
        ),
        rec(WASHER, ["Vibrates while spinning"], ["Uneven feet"], ["Adjust the feet."], page=6),
        rec(
            WASHER,
            ["Foul odor inside"],
            ["Mildew on the seal"],
            ["Wipe the seal with a product such as"],
            incomplete=True,
            page=6,
        ),
        rec(
            WASHER,
            ["Whistling"],
            ["Steam vent"],
            ["The vent whistles when hot."],
            label="Sounds",
            response="Reason",
            page=7,
        ),
        rec(FRIDGE, ["Cabinet is warm inside"], ["Vent blocked"], ["Clear the vent."]),
        rec(FRIDGE, ["Water pours out near the crisper"], ["Drain tube frozen"], ["Thaw the tube."], page=3),
        rec(FRIDGE, ["Alarm chirps"], ["Door ajar"], ["Close the door."], page=3),
        rec(FRIDGE, ["Foul odor inside"], ["Spoiled food"], ["Remove the food."], page=4),
    ]


def synthetic_index() -> SymptomIndex:
    return build_index(synthetic_records())


def appliance(appliance_id: str, manual: str) -> Appliance:
    washer = manual == WASHER
    return Appliance(
        appliance_id=appliance_id,
        brand="Acme" if washer else "Bravo",
        model="W100" if washer else "R200",
        appliance_type="washing_machine" if washer else "refrigerator",
        manual_id=manual,
    )


def synthetic_repository() -> InMemoryApplianceRepository:
    return InMemoryApplianceRepository(
        seed={
            "h-both": [appliance("a-w", WASHER), appliance("a-f", FRIDGE)],
            "h-washer": [appliance("a-w", WASHER)],
            "h-fridge": [appliance("a-f", FRIDGE)],
            "h-twins": [appliance("a-w1", WASHER), appliance("a-w2", WASHER)],
            "h-none": [],
        }
    )
