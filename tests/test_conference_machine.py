"""The machine conference is bound to the facts it judged, and never claims to be the human one.

2026-09-03: the owner asked for conference 2 and delegated it. A machine grading
the output of the same machine is weaker evidence than a human adjudication, so
the record is kept separate from the gold set, and this test enforces both the
binding to the data and the separation of claims.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
RECORD = REPO / "data" / "facts" / "gold" / "conference-machine-1.json"
LOTS = ("lot3-ad", "lot4-ads", "lot6-ads", "lot7-ads")
SINGLE = {"lot3-ad": "E7-9396"}


def record() -> dict[str, Any]:
    data: dict[str, Any] = json.loads(RECORD.read_text(encoding="utf-8"))
    return data


def shipped_value(lot: str, document: str, field_id: str) -> str | None:
    merged = json.loads((REPO / "data" / "facts" / lot / "merged.json").read_text(encoding="utf-8"))
    docs = merged.get("documents") or {SINGLE[lot]: merged}
    for fact in docs.get(document, {}).get("facts", []):
        if fact["field_id"] == field_id:
            return str(fact["value"])
    return None


def test_every_adjudicated_fact_is_still_the_fact_the_machine_shipped() -> None:
    for row in record()["adjudicated"]:
        assert shipped_value(row["lot"], row["document"], row["field_id"]) == str(row["value"]), (
            f"{row['document']}/{row['field_id']} changed since it was adjudicated; "
            "the conference record is stale"
        )


def test_the_stamp_is_bound_to_the_content_that_was_adjudicated() -> None:
    data = record()
    tuples = sorted(
        (r["lot"], r["document"], r["field_id"], str(r["value"])) for r in data["adjudicated"]
    )
    payload = json.dumps(tuples, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    assert hashlib.sha256(payload).hexdigest() == data["facts_sha256"]


def test_the_controls_prove_the_readers_detect_a_wrong_value() -> None:
    # Without this the whole conference could be a rubber stamp: readers that
    # approve everything would score the same as readers that read.
    data = record()
    controls = data["controls"]
    assert len(controls) == data["controls_planted"] >= 6
    for row in controls:
        assert row["planted"] is True
        assert row["value"] != row["true_value"]
        assert row["verdict"] == "wrong", f"a planted error passed: {row['document']}"
    assert data["controls_caught"] == len(controls)


def test_the_disputed_facts_are_listed_never_rewritten() -> None:
    data = record()
    wrong = [r for r in data["adjudicated"] if r["verdict"] != "supported"]
    assert [f"{r['document']}/{r['field_id']}" for r in wrong] == data["facts_wrong"]
    for row in wrong:
        assert row.get("reason"), "a disputed fact must carry the reason it was disputed"
        # The extractors' output is data: the record lists the dispute, the
        # shipped fact keeps the value the readers gave it.
        assert shipped_value(row["lot"], row["document"], row["field_id"]) == str(row["value"])


def test_the_record_does_not_claim_to_be_the_human_conference() -> None:
    data = record()
    assert data["conference"] == "machine-1"
    assert data["adjudicator"].startswith("machine")
    assert "NOT conference 2" in data["not_the_human_conference"]
    assert "invention_rate" not in data, (
        "the invention rate is the human adjudication's number; a machine check must not restate it"
    )
    gold = json.loads(
        (REPO / "data" / "facts" / "gold" / "conference-1.json").read_text(encoding="utf-8")
    )
    assert gold["adjudicator"].startswith("owner")
