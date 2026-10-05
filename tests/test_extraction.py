"""The comparator is the judge: agreement becomes fact, anything else a flagged blank.

The last test replays the real stage-2 pilot outputs stored in data/facts/pilot/,
so the pilot's behavior is pinned forever.
"""

import json
from pathlib import Path

from scheinman.extraction import (
    ExtractedField,
    FormField,
    load_extractor_output,
    load_form,
    merge,
    normalize,
)

REPO = Path(__file__).resolve().parents[1]


def _form(*ids: str) -> list[FormField]:
    return [FormField(field_id=i, question="q", expected_unit="text") for i in ids]


def _f(field_id: str, value: str | None, snippet: str | None = "printed text") -> ExtractedField:
    return ExtractedField(field_id=field_id, value=value, snippet=snippet, page=1)


def test_agreement_after_normalization_becomes_fact() -> None:
    result = merge(_form("x"), [_f("x", "1,733 pages")], [_f("x", "1733  PAGES")])
    assert len(result.facts) == 1 and not result.blanks


def test_numeric_json_value_matches_string_form() -> None:
    a = load_extractor_output(
        {"fields": [{"field_id": "x", "value": "0.02", "snippet": "s", "page": 1}]}
    )
    b = load_extractor_output(
        {"fields": [{"field_id": "x", "value": 0.02, "snippet": "s", "page": 1}]}
    )
    result = merge(_form("x"), a, b)
    assert len(result.facts) == 1


def test_disagreement_is_a_flagged_blank_with_both_candidates() -> None:
    result = merge(_form("x"), [_f("x", "e/D = 1.5 and 2.0")], [_f("x", "1.5 and 2.0")])
    assert not result.facts
    blank = result.blanks[0]
    assert blank.reason == "extractors disagree"
    assert blank.candidate_a and blank.candidate_b


def test_double_blank_and_half_blank_never_become_facts() -> None:
    result = merge(_form("x", "y"), [_f("x", None), _f("y", "v")], [_f("x", None), _f("y", None)])
    assert not result.facts
    reasons = {b.field_id: b.reason for b in result.blanks}
    assert reasons["x"] == "neither extractor found it"
    assert reasons["y"] == "only one extractor answered"


def test_substantive_fact_requires_anchors_from_both_readers() -> None:
    # Audit 2026-08-30: a "double-blind" fact could be minted with reader B
    # carrying no snippet at all. Substantive values now need both anchors.
    form = _form("x")
    result = merge(
        form,
        [_f("x", "7075 aluminum", snippet="made from 7075 aluminum")],
        [ExtractedField(field_id="x", value="7075 aluminum", snippet=None, page=None)],
    )
    assert result.facts == ()
    assert result.blanks[0].reason.startswith("agreed value lacks")


def test_absence_answer_stays_a_fact_with_reader_a_anchor_only() -> None:
    # 'none_stated' has nothing to quote; reader B answering it without a
    # snippet is honest, and the shipped lot4 behavior is preserved.
    form = _form("x")
    result = merge(
        form,
        [_f("x", "none_stated", snippet="Affected ADs: (b) None.")],
        [ExtractedField(field_id="x", value="none_stated", snippet=None, page=None)],
    )
    assert [f.value for f in result.facts] == ["none_stated"]


def test_normalize_respects_word_boundaries() -> None:
    # Audit 2026-08-30: 'stock' became 's-ck'. Range spellings still collapse.
    assert normalize("stock") == "stock"
    assert normalize("October through December") == "october-december"
    assert normalize("0.010 to 0.249") == "0.010-0.249"


def test_duplicate_field_id_in_one_output_is_rejected() -> None:
    import pytest

    with pytest.raises(ValueError, match="duplicate"):
        load_extractor_output(
            {
                "fields": [
                    {"field_id": "x", "value": "1", "snippet": "s", "page": 1},
                    {"field_id": "x", "value": "2", "snippet": "s", "page": 1},
                ]
            }
        )


def test_agreed_value_without_snippet_is_rejected_as_fact() -> None:
    result = merge(_form("x"), [_f("x", "v", snippet=None)], [_f("x", "v")])
    assert not result.facts and "anchor" in result.blanks[0].reason


def test_range_spellings_collapse() -> None:
    assert normalize("0.008-0.011") == normalize("0.008 to 0.011")


def test_real_pilot_replay_is_pinned() -> None:
    form = load_form(json.loads((REPO / "prompts" / "pilot_form.json").read_text()))
    a = load_extractor_output(
        json.loads((REPO / "data" / "facts" / "pilot" / "extractor_a.json").read_text())
    )
    b = load_extractor_output(
        json.loads((REPO / "data" / "facts" / "pilot" / "extractor_b.json").read_text())
    )
    result = merge(form, a, b)
    agreed = {f.field_id for f in result.facts}
    assert agreed == {
        "bus_definition",
        "bys_offset_factor",
        "ed_low_caution",
        "spec_7075_sheet",
        "t6_thinnest_range_in",
        "modulus_e_ksi",
    }
    blank_reasons = {b.field_id: b.reason for b in result.blanks}
    # The thinnest T6 column prints no L-direction values ("..."): both extractors
    # independently returned blank instead of guessing. That is the design working.
    for field in ("t6_thinnest_ftu_L_A_ksi", "t6_thinnest_fty_L_A_ksi", "t6_thinnest_fcy_L_A_ksi"):
        assert blank_reasons[field] == "neither extractor found it"
    # One wording divergence ("e/D = 1.5 and 2.0" vs "1.5 and 2.0"): flagged, not resolved.
    assert blank_reasons["ed_ratios_tabulated"] == "extractors disagree"
    assert abs(result.divergence_rate - 0.4) < 1e-9


def test_real_lot2_replay_is_pinned() -> None:
    form = load_form(json.loads((REPO / "prompts" / "lot2_form.json").read_text()))
    a = load_extractor_output(
        json.loads((REPO / "data" / "facts" / "lot2" / "extractor_a.json").read_text())
    )
    b = load_extractor_output(
        json.loads((REPO / "data" / "facts" / "lot2" / "extractor_b.json").read_text())
    )
    result = merge(form, a, b)
    assert {f.field_id: f.value for f in result.facts} == {
        "spec_6061_sheet": (
            "AMS 4026 and AMS-QQ-A-250/11; AMS-QQ-A-250/11; AMS 4025, AMS 4027 and AMS-QQ-A-250/11"
        ),
        "t6_range_with_AB_in": "0.010-0.249",
        "t6_ftu_LT_A_ksi": "42",
        "t6_fty_LT_A_ksi": "35",
        "t6_fbru_2p0_A_ksi": "88",
        "t6_e_modulus_ksi": "9.9",
        "density_lb_in3": "0.098",
    }
    # Elongation prints only a footnote marker on this page: honest blank, both readers.
    assert [b_.field_id for b_ in result.blanks] == ["t6_elongation_pct"]


def test_real_ad_pilot_replay_is_pinned() -> None:
    form = load_form(json.loads((REPO / "prompts" / "ad_pilot_form.json").read_text()))
    a = load_extractor_output(
        json.loads((REPO / "data" / "facts" / "lot3-ad" / "extractor_a.json").read_text())
    )
    b = load_extractor_output(
        json.loads((REPO / "data" / "facts" / "lot3-ad" / "extractor_b.json").read_text())
    )
    result = merge(form, a, b)
    assert {f.field_id for f in result.facts} == {"material", "failure_mechanism"}
    reasons = {bl.field_id: bl.reason for bl in result.blanks}
    # Free-text fields diverged on granularity, not on substance: flagged, never resolved
    # by the machine. Design learning: categorical fields need a closed vocabulary, and
    # "none" must be an explicit answer instead of null before this scales.
    for field in ("component", "affected_feature", "corrective_action_class"):
        assert reasons[field] == "extractors disagree"
    assert reasons["supersedes_claim"] == "neither extractor found it"


def _replay(lot_dir: str, form_file: str):  # type: ignore[no-untyped-def]
    form = load_form(json.loads((REPO / "prompts" / form_file).read_text()))
    lot = REPO / "data" / "facts" / lot_dir
    a = load_extractor_output(json.loads((lot / "extractor_a.json").read_text()))
    b = load_extractor_output(json.loads((lot / "extractor_b.json").read_text()))
    return merge(form, a, b)


def test_real_lot5_7050_plate_replay_is_pinned() -> None:
    # The floor-beam material of AD E7-9396: the failure record steered this pick.
    result = _replay("lot5-manual/7050_plate", "lot5_7050_form.json")
    assert {f.field_id: f.value for f in result.facts} == {
        "spec_7050_plate": "AMS 4050",
        "temper_7050_plate": "T7451",
        "first_range_thickness_in": "0.250-1.500",
        "ftu_L_A_ksi": "74",
        "fty_L_A_ksi": "64",
        "fbru_2p0_A_ksi": "140",
        "e_modulus_ksi": "10.3",
        "density_lb_in3": "0.102",
    }
    # The ST column of this table prints only dots: honest blank, both readers.
    assert [bl.field_id for bl in result.blanks] == ["ftu_ST_A_ksi"]


def test_real_lot5_2014_forging_replay_is_pinned() -> None:
    # The carry-thru spar material of AD 2023-02986.
    result = _replay("lot5-manual/2014_forging", "lot5_2014_form.json")
    assert result.blanks == ()
    assert {f.field_id: f.value for f in result.facts} == {
        "spec_2014_die_forging": "AMS 4133, AMS-A-22771, and AMS-QQ-A-367",
        "tempers_printed": "T6; T652",
        "first_range_thickness_in": "≤ 1.000",
        "t6_ftu_L_A_ksi": "65",
        "t6_fty_L_A_ksi": "56",
        "t6_fbru_2p0_A_ksi": "123",
        "e_modulus_ksi": "10.5",
        "density_lb_in3": "0.101",
    }


def test_real_lot6_2024_sheet_replay_is_pinned() -> None:
    result = _replay("lot6-manual/2024_sheet", "lot6_2024_form.json")
    assert {f.field_id: f.value for f in result.facts} == {
        "spec_2024_sheet": "AMS 4037 and AMS-QQ-A-250/4; AMS-QQ-A-250/4",
        "tempers_printed": "T3; T351; T361",
        "t3_first_range_with_AB_in": "0.010-0.128",
        "t3_ftu_L_A_ksi": "64",
        "t3_fty_L_A_ksi": "47",
        "t3_fbru_2p0_A_ksi": "129",
        "e_modulus_ksi": "10.5",
        "density_lb_in3": "0.100",
    }
    # The T3 ST column prints only dots: honest blank, both readers.
    assert [bl.field_id for bl in result.blanks] == ["t3_ftu_ST_A_ksi"]


def test_vocab_answer_outside_closed_list_is_rejected() -> None:
    form = [
        FormField(
            field_id="x", question="q", expected_unit="text", kind="vocab", allowed=("a", "b")
        )
    ]
    result = merge(form, [_f("x", "c")], [_f("x", "c")])
    assert not result.facts
    assert "closed vocabulary" in result.blanks[0].reason


def test_vocab_multi_compares_as_set() -> None:
    form = [
        FormField(
            field_id="x",
            question="q",
            expected_unit="text",
            kind="vocab_multi",
            allowed=("repetitive_inspection", "replacement", "modification"),
        )
    ]
    same = merge(
        form,
        [_f("x", "replacement; repetitive_inspection")],
        [_f("x", "Repetitive_Inspection;replacement")],
    )
    assert len(same.facts) == 1
    diff = merge(form, [_f("x", "replacement")], [_f("x", "modification")])
    assert diff.blanks[0].reason == "extractors disagree"


def test_answer_under_unknown_field_id_is_rejected_loudly() -> None:
    # Deep audit 2026-09-01: an answer filed under a field the form does not
    # know used to vanish, while the real field was blamed as "neither
    # extractor found it" — a false reason.
    import pytest

    with pytest.raises(ValueError, match="ftu_l_typo"):
        merge(_form("ftu_l"), [_f("ftu_l_typo", "74")], [_f("ftu_l", "74")])


def test_form_with_duplicate_field_id_is_rejected() -> None:
    import pytest

    raw: dict[str, object] = {
        "fields": [
            {"field_id": "x", "question": "a", "expected_unit": "text"},
            {"field_id": "x", "question": "b", "expected_unit": "text"},
        ]
    }
    with pytest.raises(ValueError, match="duplicate"):
        load_form(raw)


def test_normalize_keeps_decimal_commas_apart_from_thousands() -> None:
    # "1,733" is one thousand seven hundred; "1,5" is a European decimal and
    # must NOT collapse into "15" (deep audit 2026-09-01).
    assert normalize("1,733") == "1733"
    assert normalize("1,5") != normalize("15")
