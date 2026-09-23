import json

import pytest
from pydantic import ValidationError

from fixit_mcp.ingestion.extraction import (
    BedrockExtractor,
    ErrorCodeRecord,
    StubExtractor,
    _parse_records,
    normalize_code,
)
from fixit_mcp.ingestion.parser import ManualChunk, UncertainRepair


def make_chunk(text: str, is_table: bool = True, **overrides) -> ManualChunk:
    defaults = dict(
        manual_id="lg-dlex8000w-dryer",
        brand="LG",
        model="DLEX8000W",
        appliance_type="dryer",
        chunk_id="lg-dlex8000w-dryer::chunk-0196",
        text=text,
        page_start=31,
        page_end=31,
        section_heading="Installation test (Exhaust check) (cont.)",
        section_path=["Installation test (Exhaust check) (cont.)"],
        is_table=is_table,
    )
    defaults.update(overrides)
    return ManualChunk(**defaults)


# --- normalize_code -------------------------------------------------


def test_normalize_code_strips_separators_and_uppercases() -> None:
    assert normalize_code("E:24-00") == "E2400"
    assert normalize_code("tE1") == "TE1"
    assert normalize_code("E24") == "E24"
    assert normalize_code("PS") == "PS"


# --- StubExtractor -------------------------------------------------


def test_stub_extractor_finds_known_lg_codes() -> None:
    chunk = make_chunk("Error Code\nPossible Causes\nSolutions\ntE1 or tE2\nHS\nPS or PF or nP")

    records = StubExtractor().extract(chunk)

    codes = {r.error_code for r in records}
    assert codes == {"tE1", "tE2", "HS", "PS", "PF", "nP"}


def test_stub_extractor_finds_bosch_style_codes() -> None:
    chunk = make_chunk("Issue\nCause and troubleshooting\nE:20-60 lights up alternately.\nE:24-00 also.")

    records = StubExtractor().extract(chunk)

    assert {r.error_code for r in records} == {"E:20-60", "E:24-00"}


def test_stub_extractor_never_fills_in_unstated_fields() -> None:
    chunk = make_chunk("tE1 appears here.")

    records = StubExtractor().extract(chunk)

    assert len(records) == 1
    record = records[0]
    assert record.meaning == ""
    assert record.likely_causes == []
    assert record.repair_steps == []
    assert record.parts_needed == []
    assert record.safety_warnings == []
    assert record.difficulty is None


def test_stub_extractor_stamps_manual_metadata_and_source_from_chunk() -> None:
    chunk = make_chunk("tE1 appears here.")

    record = StubExtractor().extract(chunk)[0]

    assert record.manual_id == chunk.manual_id
    assert record.brand == chunk.brand
    assert record.model == chunk.model
    assert record.appliance_type == chunk.appliance_type
    assert record.source_page == chunk.page_start
    assert record.source_section == chunk.section_heading
    assert record.source_chunk_id == chunk.chunk_id
    assert record.code_normalized == "TE1"


def test_stub_extractor_returns_empty_for_ordinary_prose() -> None:
    chunk = make_chunk("This is a normal paragraph about installing the dryer. No codes here.")

    assert StubExtractor().extract(chunk) == []


def test_stub_extractor_dedupes_repeated_codes_within_one_chunk() -> None:
    chunk = make_chunk("tE1 appears here. Later, tE1 appears again.")

    records = StubExtractor().extract(chunk)

    assert len(records) == 1


# --- ErrorCodeRecord schema validation -------------------------------------------------


def test_error_code_record_rejects_confidence_out_of_range() -> None:
    with pytest.raises(ValidationError):
        ErrorCodeRecord(
            manual_id="m",
            brand="LG",
            model="X",
            appliance_type="dryer",
            error_code="tE1",
            code_normalized="TE1",
            source_page=1,
            source_section=None,
            source_chunk_id="m::chunk-0001",
            extraction_confidence=1.5,
        )


def test_parse_records_rejects_non_array_json() -> None:
    chunk = make_chunk("tE1")

    with pytest.raises(ValueError):
        _parse_records(json.dumps({"error_code": "tE1"}), chunk)


def test_parse_records_rejects_unexpected_keys() -> None:
    chunk = make_chunk("tE1")
    bad = json.dumps([{"error_code": "tE1", "extraction_confidence": 0.9, "made_up_field": "oops"}])

    with pytest.raises(ValueError):
        _parse_records(bad, chunk)


def test_parse_records_rejects_schema_violation() -> None:
    chunk = make_chunk("tE1")
    bad = json.dumps([{"error_code": "tE1", "extraction_confidence": "not-a-number"}])

    with pytest.raises(ValidationError):
        _parse_records(bad, chunk)


def test_parse_records_accepts_valid_minimal_record() -> None:
    chunk = make_chunk("tE1")
    good = json.dumps(
        [
            {
                "error_code": "tE1",
                "meaning": "Temperature sensor failure",
                "likely_causes": ["Temperature sensor failure"],
                "repair_steps": ["Turn off the dryer and call for service."],
                "parts_needed": [],
                "safety_warnings": [],
                "difficulty": "call_service",
                "extraction_confidence": 0.9,
            }
        ]
    )

    records = _parse_records(good, chunk)

    assert len(records) == 1
    assert records[0].error_code == "tE1"
    assert records[0].code_normalized == "TE1"
    assert records[0].difficulty == "call_service"
    assert records[0].manual_id == chunk.manual_id


# --- BedrockExtractor (mocked client, no AWS credentials needed) -----------

GOOD_RESPONSE = json.dumps(
    [
        {
            "error_code": "tE1",
            "meaning": "Temperature sensor failure",
            "likely_causes": ["Temperature sensor failure"],
            "repair_steps": ["Turn off the dryer and call for service."],
            "parts_needed": [],
            "safety_warnings": [],
            "difficulty": "call_service",
            "extraction_confidence": 0.9,
        }
    ]
)


class FakeConverseClient:
    """Stands in for a boto3 bedrock-runtime client -- no network, no AWS
    credentials. Returns each response in order; raises if exhausted."""

    def __init__(self, responses: list[str]) -> None:
        self._responses = list(responses)
        self.calls: list[dict] = []

    def converse(self, **kwargs):
        self.calls.append(kwargs)
        text = self._responses.pop(0)
        return {
            "output": {"message": {"content": [{"text": text}]}},
            "usage": {"inputTokens": 100, "outputTokens": 50},
        }


def test_bedrock_extractor_parses_valid_response() -> None:
    client = FakeConverseClient([GOOD_RESPONSE])
    extractor = BedrockExtractor(region="us-east-1", model_id="test-model", client=client)

    records = extractor.extract(make_chunk("tE1: Temperature sensor failure."))

    assert len(records) == 1
    assert records[0].error_code == "tE1"
    assert records[0].code_normalized == "TE1"
    assert len(client.calls) == 1
    assert extractor.last_usage == {"input_tokens": 100, "output_tokens": 50}


def test_bedrock_extractor_returns_empty_list_for_no_codes() -> None:
    client = FakeConverseClient(["[]"])
    extractor = BedrockExtractor(region="us-east-1", model_id="test-model", client=client)

    assert extractor.extract(make_chunk("Just ordinary prose, no codes here.")) == []


def test_bedrock_extractor_strips_markdown_fences() -> None:
    fenced = f"```json\n{GOOD_RESPONSE}\n```"
    client = FakeConverseClient([fenced])
    extractor = BedrockExtractor(region="us-east-1", model_id="test-model", client=client)

    records = extractor.extract(make_chunk("tE1"))

    assert len(records) == 1


def test_bedrock_extractor_passes_uncertain_repairs_into_the_prompt() -> None:
    client = FakeConverseClient([GOOD_RESPONSE])
    extractor = BedrockExtractor(region="us-east-1", model_id="test-model", client=client)
    chunk = make_chunk(
        "14 or 1' or O1",
        uncertain_repairs=[UncertainRepair(original="14", repaired="PS", confidence=0.5)],
    )

    extractor.extract(chunk)

    sent_prompt = client.calls[0]["messages"][0]["content"][0]["text"]
    assert "UNCERTAIN REPAIRS" in sent_prompt
    assert '"14" -> "PS"' in sent_prompt


# --- retry path -------------------------------------------------


def test_bedrock_extractor_retries_after_malformed_json_then_succeeds() -> None:
    client = FakeConverseClient(["not json at all", GOOD_RESPONSE])
    extractor = BedrockExtractor(region="us-east-1", model_id="test-model", max_retries=2, client=client)

    records = extractor.extract(make_chunk("tE1"))

    assert len(records) == 1
    assert len(client.calls) == 2
    # The retry prompt includes a hint that the previous response was bad.
    assert "could not be parsed" in client.calls[1]["messages"][0]["content"][0]["text"]


def test_bedrock_extractor_retries_after_schema_violation_then_succeeds() -> None:
    bad_schema = json.dumps([{"error_code": "tE1", "extraction_confidence": "not-a-number"}])
    client = FakeConverseClient([bad_schema, GOOD_RESPONSE])
    extractor = BedrockExtractor(region="us-east-1", model_id="test-model", max_retries=2, client=client)

    records = extractor.extract(make_chunk("tE1"))

    assert len(records) == 1
    assert len(client.calls) == 2


def test_bedrock_extractor_gives_up_after_max_retries_and_returns_empty() -> None:
    client = FakeConverseClient(["still not json", "still not json", "still not json"])
    extractor = BedrockExtractor(region="us-east-1", model_id="test-model", max_retries=2, client=client)

    records = extractor.extract(make_chunk("tE1"))

    assert records == []
    assert len(client.calls) == 3  # 1 initial attempt + 2 retries
