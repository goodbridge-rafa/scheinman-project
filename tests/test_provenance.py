"""Every excerpt the product shows is checked against the stored source.

Audit 2026-09-02: the evidence page said "each
with its verbatim excerpt" and no command in the repository measured it. Now
scheinman.provenance measures it and writes data/facts/provenance.json; this
test keeps that file honest (fresh, and never silently worse) and holds the
hand-typed rule anchors to a stricter bar: verbatim, no exceptions.
"""

from __future__ import annotations

import json
from pathlib import Path

from scheinman.provenance import (
    OUTPUT,
    RAW_ADS,
    check_rule_anchors,
    check_threshold_excerpts,
    flat,
    flat_pdf,
    report,
)

REPO = Path(__file__).resolve().parents[1]


def test_every_rule_event_excerpt_occurs_in_the_stored_record() -> None:
    assert check_rule_anchors() == []


def test_the_committed_provenance_report_is_fresh_and_the_ad_facts_are_mostly_contiguous() -> None:
    fresh = report()
    committed = json.loads(OUTPUT.read_text(encoding="utf-8"))
    assert committed == fresh, (
        "data/facts/provenance.json is stale: regenerate with "
        "`uv run python -m scheinman.provenance`"
    )
    assert fresh["facts_checked"] > 400
    # The deviations are listed, never hidden; a new one must be seen, not absorbed.
    assert fresh["facts_deviating"] <= 20, (
        "more excerpts deviate from the record than the last measured count"
    )
    assert fresh["facts_found_contiguous"] + fresh["facts_deviating"] == fresh["facts_checked"]


def test_normalisation_touches_only_wrapping_markers_escapes_and_case() -> None:
    assert (
        flat("head-\nto-barrel  [[Page 56997]] Corrosion \\3/16\\")
        == "head-to-barrel corrosion 3/16"
    )
    assert flat("a - b") == "a -b", (
        "a spaced dash is not a wrapped hyphen, and both sides get the same treatment"
    )


def test_the_two_copies_of_ad_e7_9396_are_byte_identical() -> None:
    # seed_rules.json says so in prose; a sentence is not a check.
    assert (RAW_ADS.parent / "AD-E7-9396.txt").read_bytes() == (
        RAW_ADS / "E7-9396.txt"
    ).read_bytes()


def test_the_canonical_threshold_excerpts_are_verbatim_on_their_stated_pdf_pages() -> None:
    # Until 2026-09-03 the four AC sentences were the one hand-typed link no
    # command checked (the seed_rules.json header said so). The stored PDF has
    # a text layer, so the sentence is now searched on the page the locator names.
    result = check_threshold_excerpts()
    assert result["checked"] == 4
    assert result["failures"] == []


def test_a_threshold_excerpt_that_is_not_on_its_page_is_reported() -> None:
    rule = {
        "rule_id": "R-TEST",
        "threshold_anchor": {
            "kind": "canonical_citation",
            "locator": "PDF page 159 of 646",
            "excerpt": "the edge distance should not be less than 2.5 times the diameter",
        },
    }
    assert check_threshold_excerpts([rule]) == {
        "checked": 1,
        "failures": ["R-TEST: threshold excerpt is not verbatim on PDF page 159"],
    }


def test_pdf_normalisation_removes_only_the_soft_hyphen_line_break() -> None:
    assert (
        flat_pdf("the edge dis\u00ad tance and the di\u00ad\nameter")
        == "the edge distance and the diameter"
    )
    assert flat_pdf("head-\nto-barrel") == flat("head-\nto-barrel")
