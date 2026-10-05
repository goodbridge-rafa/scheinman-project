"""Replay of lot6: the one vault AD the aluminum-substring query missed
(Airbus writes 'aluminium'). Pins the merge and the honest fusion zero."""

import json
from pathlib import Path

from scheinman.ad_extraction import merge_lot, parse_batch_output, validate_against_spec
from scheinman.extraction import load_form
from scheinman.fusion import event_from_merged, fuse
from scheinman.rules import load_rules

REPO = Path(__file__).resolve().parents[1]
LOT = REPO / "data" / "facts" / "lot6-ads"


def test_real_lot6_straggler_replay_is_pinned() -> None:
    spec = json.loads((LOT / "batches.json").read_text())
    form = load_form(json.loads((REPO / spec["form"]).read_text()))
    allowed = {p.rsplit("/", 1)[-1].removesuffix(".txt") for p in spec["batches"]["b01"]}
    sides = {}
    for persona in "ab":
        raw = json.loads((LOT / "raw" / f"b01_{persona}.json").read_text())
        kept, rejected, missing = validate_against_spec(parse_batch_output(raw), allowed)
        assert rejected == [] and missing == []
        sides[persona] = kept
    results, stats = merge_lot(form, sides["a"], sides["b"])
    assert (stats.documents, stats.facts, stats.blanks) == (1, 5, 1)
    result = results["2019-18045"]
    values = {f.field_id: f.value for f in result.facts}
    assert values["component_class"] == "pylon"
    assert values["mechanism_class"] == "fatigue_cracking"
    # The readers disagreed only on the 'AD ' prefix; the machine never resolves.
    assert result.blanks[0].field_id == "supersedes"
    assert result.blanks[0].reason == "extractors disagree"
    # Fusion: a pylon event with feature 'other' evidences no rule quantity.
    events = [event_from_merged("2019-18045", result)]
    assert all(docs == [] for docs in fuse(load_rules(), events).values())
