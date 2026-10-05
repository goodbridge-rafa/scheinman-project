"""Replay of the 60-AD aluminum lot (lot4): raw extractor outputs on disk are
re-judged end to end — spec boundary, A/B merge, lot stats, fusion — and the
result is pinned. If any number here drifts, the data or the judging changed."""

import json
from pathlib import Path

from scheinman.ad_extraction import (
    LotStats,
    merge_lot,
    parse_batch_output,
    validate_against_spec,
)
from scheinman.extraction import ExtractedField, MergeResult, load_form
from scheinman.fusion import event_from_merged, fuse
from scheinman.rules import load_rules

REPO = Path(__file__).resolve().parents[1]
LOT = REPO / "data" / "facts" / "lot4-ads"


def _lot_results() -> tuple[dict[str, MergeResult], LotStats]:
    spec = json.loads((LOT / "batches.json").read_text())
    form = load_form(json.loads((REPO / spec["form"]).read_text()))
    a_by_doc: dict[str, list[ExtractedField]] = {}
    b_by_doc: dict[str, list[ExtractedField]] = {}
    for batch, paths in sorted(spec["batches"].items()):
        allowed = {p.rsplit("/", 1)[-1].removesuffix(".txt") for p in paths}
        for persona, sink in (("a", a_by_doc), ("b", b_by_doc)):
            raw = json.loads((LOT / "raw" / f"{batch}_{persona}.json").read_text())
            kept, rejected, missing = validate_against_spec(parse_batch_output(raw), allowed)
            assert rejected == [], f"{batch}_{persona} answered outside its spec"
            assert missing == [], f"{batch}_{persona} missed documents"
            sink.update(kept)
    return merge_lot(form, a_by_doc, b_by_doc)


def test_real_lot4_replay_is_pinned() -> None:
    results, stats = _lot_results()
    assert stats.documents == 60
    assert stats.facts == 311
    assert stats.blanks == 49
    assert round(stats.divergence_rate, 4) == 0.1361
    saved = json.loads((LOT / "merged.json").read_text())
    assert saved["stats"]["facts"] == stats.facts
    assert saved["stats"]["blanks"] == stats.blanks


def test_real_lot4_fusion_support_is_pinned() -> None:
    results, _ = _lot_results()
    events = [event_from_merged(n, r) for n, r in sorted(results.items())]
    support = fuse(load_rules(), events)
    # The 7xxx cyclic edge-distance rule is backed by two real failure records:
    # a 7075 floor beam and a 7050-T7451 floor beam, both fatigue at fastener holes.
    assert support["R-0001"] == ["00-4568", "E7-9396"]
    assert len(support["R-0002"]) == 16
    # Audit 2026-08-30: the pitch and diameter-over-thickness rules once
    # inherited the same 16 events; a fastener-hole fatigue event says nothing
    # about those quantities, so their support is honestly zero.
    assert support["R-0003"] == []
    assert support["R-0004"] == []
    assert len(support["R-0005"]) == 2
    saved = json.loads((LOT / "fusion.json").read_text())
    assert saved["support"]["R-0001"]["documents"] == support["R-0001"]
