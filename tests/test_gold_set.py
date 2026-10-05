"""The gold set is the owner's independent verdict; this pins it and recomputes
the invention rate from the record instead of trusting a written number."""

import json
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]


def test_conference_1_gold_set_is_recorded_and_rate_recomputes() -> None:
    gold = json.loads((REPO / "data" / "facts" / "gold" / "conference-1.json").read_text())
    assert gold["adjudicator"].startswith("owner")
    assert gold["facts_total"] == 13
    rate = len(gold["facts_wrong"]) / gold["facts_total"]
    assert rate == gold["invention_rate"] == 0.0
    # The adjudicated facts must be the ones the machine actually shipped.
    pilot = json.loads((REPO / "data" / "facts" / "pilot" / "merged.json").read_text())
    lot2 = json.loads((REPO / "data" / "facts" / "lot2" / "merged.json").read_text())
    assert len(pilot["facts"]) + len(lot2["facts"]) == gold["facts_total"]


def test_the_stamp_is_bound_to_the_content_that_was_adjudicated() -> None:
    # Audit 2026-09-02: the stamp used to pin a count (13), so a
    # re-run of the readers that kept the count would have kept the stamp.
    import hashlib

    gold = json.loads((REPO / "data" / "facts" / "gold" / "conference-1.json").read_text())
    tuples = []
    for lot in ("pilot", "lot2"):
        merged = json.loads((REPO / "data" / "facts" / lot / "merged.json").read_text())
        for fact in merged["facts"]:
            tuples.append(
                (lot, fact["field_id"], str(fact["value"]), fact["snippet"], int(fact["page"]))
            )
    payload = json.dumps(sorted(tuples), ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    assert hashlib.sha256(payload).hexdigest() == gold["facts_sha256"]
