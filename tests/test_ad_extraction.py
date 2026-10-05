"""Series derivation, lot selection and batch parsing are code, not judgment."""

from typing import Any

from scheinman.ad_extraction import batches, parse_batch_output, select_lot, series_from_alloy


def test_series_is_derived_deterministically() -> None:
    assert series_from_alloy("7075-T6") == "7xxx"
    assert series_from_alloy("7050-T7451 aluminum alloy") == "7xxx"
    assert series_from_alloy("7000 series aluminum alloy") == "7xxx"
    assert series_from_alloy("2024-T3 clad") == "2xxx"
    assert series_from_alloy("none_stated") == "unknown"


def test_lot_selection_skips_fetch_errors_and_filters_by_query() -> None:
    index: dict[str, dict[str, Any]] = {
        "A": {"found_by": ["aluminum fatigue cracking"], "fetch_error": "404"},
        "B": {"found_by": ["fatigue cracking spar"]},
        "C": {"found_by": ["airworthiness directive aluminum fatigue cracking"]},
    }
    assert select_lot(index, "aluminum") == ["C"]
    assert select_lot(index, "spar") == ["B"]


def test_batches_partition_in_order() -> None:
    assert batches(["a", "b", "c", "d", "e"], 2) == [["a", "b"], ["c", "d"], ["e"]]


def test_parse_batch_output_maps_documents() -> None:
    raw = {
        "ads": {
            "E7-9396": {
                "fields": [
                    {
                        "field_id": "alloy_as_stated",
                        "value": "7050-T7451",
                        "snippet": "s",
                        "page": 1,
                    }
                ]
            }
        }
    }
    parsed = parse_batch_output(raw)
    assert parsed["E7-9396"][0].value == "7050-T7451"


def test_batch_prompt_carries_exactly_the_spec_files() -> None:
    import re
    from pathlib import Path

    from scheinman.ad_extraction import build_batch_prompt

    repo = Path(__file__).resolve().parents[1]
    # Modern (YYYY-NNNNN), classic (NN-NNNN) and E-prefixed numbers together:
    # the lesson-006 guard must see every shape (deep audit 2026-09-01).
    paths = ["data/raw/ads/00-13445.txt", "data/raw/ads/2019-18045.txt", "data/raw/AD-E7-9396.txt"]
    prompt = build_batch_prompt("prompts/extractor_a.md", "prompts/ad_form_v2.json", paths)
    for p in paths:
        assert f"{repo}/{p}" in prompt, "paths must derive from the repo root, never hardcoded"
    numbers = set(re.findall(r"\b(?:E?\d{1,2}|(?:19|20)\d{2})-\d{4,5}\b", prompt))
    assert numbers == {"00-13445", "2019-18045", "E7-9396"}, (
        "no document number beyond the spec may appear, in any AD numbering era"
    )


def test_validate_against_spec_reports_missing_documents_too() -> None:
    from scheinman.ad_extraction import validate_against_spec
    from scheinman.extraction import ExtractedField

    parsed = {"00-1": [ExtractedField(field_id="x", value="1", snippet="s", page=1)]}
    kept, rejected, missing = validate_against_spec(parsed, {"00-1", "00-2"})
    assert set(kept) == {"00-1"} and rejected == [] and missing == ["00-2"]
