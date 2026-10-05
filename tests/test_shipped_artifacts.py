"""Every committed facts artifact must equal its replay from the raw reader
outputs — content, not just counts. A hand edit of any shipped merged.json or
of the lot4 fusion artifact must fail here (deep audit 2026-09-01)."""

import json
import re
from pathlib import Path

from scheinman.ad_extraction import (
    lot_payload,
    merge_lot,
    parse_batch_output,
    validate_against_spec,
)
from scheinman.extraction import ExtractedField, load_extractor_output, load_form, merge
from scheinman.fusion import event_from_merged, fuse
from scheinman.rules import load_rules

REPO = Path(__file__).resolve().parents[1]

SIMPLE_LOTS = (
    ("pilot", "pilot_form.json"),
    ("lot2", "lot2_form.json"),
    ("lot3-ad", "ad_pilot_form.json"),
    ("lot5-manual/7050_plate", "lot5_7050_form.json"),
    ("lot5-manual/2014_forging", "lot5_2014_form.json"),
    ("lot6-manual/2024_sheet", "lot6_2024_form.json"),
)


def _fact_key(fact: dict) -> tuple:  # type: ignore[type-arg]
    return (fact["field_id"], fact["value"], fact["snippet"], fact["page"])


def test_every_simple_lot_merged_json_equals_its_replay() -> None:
    for lot, form_name in SIMPLE_LOTS:
        form = load_form(json.loads((REPO / "prompts" / form_name).read_text()))
        base = REPO / "data" / "facts" / lot
        a = load_extractor_output(json.loads((base / "extractor_a.json").read_text()))
        b = load_extractor_output(json.loads((base / "extractor_b.json").read_text()))
        replayed = merge(form, a, b)
        saved = json.loads((base / "merged.json").read_text())
        got = {(f.field_id, f.value, f.snippet, f.page) for f in replayed.facts}
        want = {_fact_key(f) for f in saved["facts"]}
        assert got == want, f"{lot}: committed facts differ from the replay"
        assert [bl.field_id for bl in replayed.blanks] == [
            bl["field_id"] for bl in saved["blanks"]
        ], f"{lot}: committed blanks differ from the replay"


def _replay_ad_lot(lot: str) -> dict:  # type: ignore[type-arg]
    base = REPO / "data" / "facts" / lot
    spec = json.loads((base / "batches.json").read_text())
    form = load_form(json.loads((REPO / spec["form"]).read_text()))
    a_by_doc: dict[str, list[ExtractedField]] = {}
    b_by_doc: dict[str, list[ExtractedField]] = {}
    for batch, paths in sorted(spec["batches"].items()):
        allowed = {p.rsplit("/", 1)[-1].removesuffix(".txt") for p in paths}
        for persona, sink in (("a", a_by_doc), ("b", b_by_doc)):
            raw = json.loads((base / "raw" / f"{batch}_{persona}.json").read_text())
            kept, rejected, missing = validate_against_spec(parse_batch_output(raw), allowed)
            assert rejected == [] and missing == [], (lot, batch, persona)
            sink.update(kept)
    results, stats = merge_lot(form, a_by_doc, b_by_doc)
    # The shape comes from the code that writes it, never from a copy here.
    return lot_payload(results, stats)


def test_every_ad_lot_merged_json_equals_its_replay() -> None:
    for lot in ("lot4-ads", "lot6-ads", "lot7-ads"):
        saved = json.loads((REPO / "data" / "facts" / lot / "merged.json").read_text())
        assert _replay_ad_lot(lot) == saved, f"{lot}/merged.json differs from its replay"


def test_lot4_fusion_artifact_equals_its_replay() -> None:
    replayed = _replay_ad_lot("lot4-ads")
    saved = json.loads((REPO / "data" / "facts" / "lot4-ads" / "fusion.json").read_text())
    from scheinman.extraction import MergeResult

    results = {n: MergeResult.model_validate(doc) for n, doc in replayed["documents"].items()}
    events = [event_from_merged(n, r) for n, r in sorted(results.items())]
    support = fuse(load_rules(), events)
    assert saved["support"] == {
        rid: {"count": len(docs), "documents": docs} for rid, docs in support.items()
    }, "lot4 fusion support drifted from its replay"
    assert len(saved["events"]) == len(events)


def test_manual_lot_annotated_snippets_carry_the_convention_marker() -> None:
    # Lesson 007: reader location commentary lives inside some manual-lot
    # snippets; any file carrying that pattern must declare the convention so
    # no one mistakes the parenthetical for page text.
    for lot in ("lot5-manual/7050_plate", "lot5-manual/2014_forging", "lot6-manual/2024_sheet"):
        saved = json.loads((REPO / "data" / "facts" / lot / "merged.json").read_text())
        annotated = [f["field_id"] for f in saved["facts"] if re.search(r"\(", str(f["snippet"]))]
        if annotated:
            assert "snippet_convention" in saved, (
                f"{lot} has annotated snippets {annotated} but no convention marker"
            )
