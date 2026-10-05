"""Replay of lot7 (the 33 wave-2 aluminum ADs) and of the combined fusion
artifact across lots 4, 6 and 7. Each lot's merged.json is itself pinned by
its own replay; here the chain closes: events rebuilt from those artifacts
must reproduce data/facts/fusion-combined.json exactly."""

import json
from pathlib import Path

from scheinman.ad_extraction import (
    merge_lot,
    parse_batch_output,
    series_from_alloy,
    validate_against_spec,
)
from scheinman.extraction import load_form
from scheinman.fusion import AdEvent, fuse
from scheinman.rules import load_rules

REPO = Path(__file__).resolve().parents[1]
LOT = REPO / "data" / "facts" / "lot7-ads"


def test_real_lot7_replay_is_pinned() -> None:
    spec = json.loads((LOT / "batches.json").read_text())
    form = load_form(json.loads((REPO / spec["form"]).read_text()))
    from scheinman.extraction import ExtractedField

    a_by_doc: dict[str, list[ExtractedField]] = {}
    b_by_doc: dict[str, list[ExtractedField]] = {}
    for batch, paths in sorted(spec["batches"].items()):
        allowed = {p.rsplit("/", 1)[-1].removesuffix(".txt") for p in paths}
        for persona, sink in (("a", a_by_doc), ("b", b_by_doc)):
            raw = json.loads((LOT / "raw" / f"{batch}_{persona}.json").read_text())
            kept, rejected, missing = validate_against_spec(parse_batch_output(raw), allowed)
            assert rejected == [] and missing == [], (batch, persona)
            sink.update(kept)
    results, stats = merge_lot(form, a_by_doc, b_by_doc)
    assert (stats.documents, stats.facts, stats.blanks) == (33, 189, 9)
    saved = json.loads((LOT / "merged.json").read_text())
    assert saved["stats"]["facts"] == stats.facts


def _events_from_artifact(lot_dir: str) -> list[AdEvent]:
    merged = json.loads((REPO / lot_dir / "merged.json").read_text())
    events = []
    for doc, result in sorted(merged["documents"].items()):
        values = {f["field_id"]: f["value"] for f in result["facts"]}
        alloy = values.get("alloy_as_stated")
        events.append(
            AdEvent(
                document_number=doc,
                alloy_as_stated=alloy,
                series=series_from_alloy(alloy) if alloy else "unknown",
                feature_class=values.get("feature_class"),
                mechanism_class=values.get("mechanism_class"),
                snippets=tuple(f["snippet"] for f in result["facts"]),
            )
        )
    return events


def test_combined_fusion_artifact_is_reproducible() -> None:
    saved = json.loads((REPO / "data" / "facts" / "fusion-combined.json").read_text())
    events = [e for lot in saved["inputs"]["lots"] for e in _events_from_artifact(lot)]
    assert len(events) == saved["events_total"] == 94
    support = fuse(load_rules(), events)
    for rule_id, docs in support.items():
        assert saved["support"][rule_id]["documents"] == docs
    assert support["R-0001"] == ["00-4568", "E7-9396"]
    assert len(support["R-0002"]) == 18
    assert support["R-0003"] == [] and support["R-0004"] == []
    assert len(support["R-0005"]) == 4
