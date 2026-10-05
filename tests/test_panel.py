"""The panel is generated, never hand-edited: these tests pin freshness against
the committed file, recompute its headline numbers independently from primary
sources, and keep every displayed quote verbatim to its stored anchor."""

import json
import re
from html import unescape

import pytest

from scheinman.panel import (
    DEMO_PART_NAME,
    OUTPUT_PATH,
    REPO_ROOT,
    build_panel_html,
    render_document,
)
from scheinman.parts import stage1_parts
from scheinman.rules import load_rules


@pytest.fixture(scope="session", name="html")
def built_html() -> str:
    return build_panel_html()


def test_committed_panel_is_fresh(html: str) -> None:
    assert OUTPUT_PATH.read_text() == render_document(html), (
        "panel/index.html is stale: regenerate with `uv run python -m scheinman.panel` "
        "in the same commit as the change that moved the data"
    )


def test_no_placeholder_survives_rendering(html: str) -> None:
    assert "$" not in html


def test_totals_recompute_from_primary_sources(html: str) -> None:
    facts = blanks = docs = 0
    for directory in ("lot4-ads", "lot6-ads", "lot7-ads"):
        stats = json.loads((REPO_ROOT / "data" / "facts" / directory / "merged.json").read_text())[
            "stats"
        ]
        facts += stats["facts"]
        blanks += stats["blanks"]
        docs += stats["documents"]
    assert f">{facts}<" in html
    assert f">{blanks}<" in html
    assert f"across {docs} records" in html
    assert f"({blanks / (facts + blanks) * 100:.1f}% overall)" in html


def test_invention_rate_comes_from_the_gold_set(html: str) -> None:
    gold = json.loads((REPO_ROOT / "data" / "facts" / "gold" / "conference-1.json").read_text())
    rate = len(gold["facts_wrong"]) / gold["facts_total"]
    right = gold["facts_total"] - len(gold["facts_wrong"])
    assert f">{rate:.1f}</p>" in html
    assert f"OWNER · {right}/{gold['facts_total']} · {gold['date_adjudicated']}" in html


def test_displayed_quotes_are_verbatim_from_anchors(html: str) -> None:
    r1 = next(r for r in load_rules() if r.rule_id == "R-0001")
    stored = [
        r1.threshold_anchor.excerpt,
        r1.event_anchors[0].excerpt,
        r1.event_anchors[1].excerpt,
    ]
    shown = re.findall(r"“(.*?)”", html, flags=re.S)
    assert len(shown) == len(stored)
    for quote, excerpt in zip(shown, stored, strict=True):
        for piece in unescape(quote).split(" … "):
            assert piece in excerpt, f"not verbatim: {piece[:60]!r}"


def test_honest_zeros_render_as_stubs_not_bars(html: str) -> None:
    support = json.loads((REPO_ROOT / "data" / "facts" / "fusion-combined.json").read_text())[
        "support"
    ]
    zero_rules = [rid for rid, entry in support.items() if entry["count"] == 0]
    assert html.count('class="zero-stub"') == len(zero_rules)


def test_correction_story_shows_rejected_then_proven(html: str) -> None:
    assert "violations · REJECTED" in html
    assert "0 violations · PROVEN" in html


def test_drawing_geometry_still_matches_the_demo_part() -> None:
    # The template's SVG is drawn at 5.2 px/mm to THIS geometry. Changing the
    # demo part means redrawing the hero: this pin forces that conversation.
    spec = next(s for s in stage1_parts() if s.name == DEMO_PART_NAME)
    assert (spec.length, spec.width) == (100, 60)
    assert [(h.x, h.y, h.diameter) for h in spec.holes] == [(10, 8, 6), (60, 30, 6)]


def test_panel_is_a_complete_document_with_data_synced_prose(html: str) -> None:
    committed = OUTPUT_PATH.read_text()
    assert committed.startswith("<!doctype html>")
    assert '<html lang="en">' in committed and '<meta charset="utf-8">' in committed
    # Fixture rules are declared, never passed off as engineering facts.
    assert "synthetic test-fixture rule" in html
    assert "TEST FIXTURE · R-0005" in html
    # The drawing's screen-reader label carries the measured numbers.
    assert "recentered by the machine to 12.24 millimeters" in html


def test_the_machine_cross_check_is_shown_as_such_and_never_as_the_human_verdict(html: str) -> None:
    # 2026-09-03: the page carries two adjudications of different strength. The
    # weaker one must be visible, numbered, and named for what it is.
    machine = json.loads(
        (REPO_ROOT / "data" / "facts" / "gold" / "conference-machine-1.json").read_text()
    )
    assert f">{machine['facts_total']}<" in html
    assert "machine cross-check, not the human adjudication" in html
    assert (
        f"{machine['controls_caught']} of {machine['controls_planted']} planted errors caught"
        in html
    )
    # The human line says which facts it covers, so no reader can read it as all of them.
    assert "handbook facts" in html
