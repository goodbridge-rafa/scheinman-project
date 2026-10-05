"""Build the public panel (panel/index.html) from repository data.

Every number on the page is recomputed here from primary sources:
vault counts from data/raw (AD records counted live; PDF page counts from the
measured manifest data/raw/vault.json), extraction totals and per-lot
flagged-blank rates from data/facts/*/merged.json, fused failure-event weights
from data/facts/fusion-combined.json, the adjudicated gold set from
data/facts/gold/conference-1.json, rule R-0001 text verbatim from
data/rules/seed_rules.json anchors, and the correction proof by actually
re-running measure -> judge -> correct -> re-measure on the demo part in a
temporary directory.

The template (panel_template.html, the owner-approved v2 design) carries the
looks; this module carries the truth. Publication gate: the build refuses to
render if the measured invention rate is not zero, and it validates stored
rates against recomputation before using them.
"""

from __future__ import annotations

import json
import tempfile
from dataclasses import dataclass
from html import escape
from pathlib import Path
from string import Template
from typing import Any

from scheinman.correction import correct_until_clean
from scheinman.measure import measure_step_file
from scheinman.parts import PartSpec, export_part, stage1_parts
from scheinman.rules import load_rules
from scheinman.schemas import Rule
from scheinman.verdict import evaluate

REPO_ROOT = Path(__file__).resolve().parents[2]
TEMPLATE_PATH = Path(__file__).with_name("panel_template.html")
OUTPUT_PATH = REPO_ROOT / "panel" / "index.html"
DEMO_PART_NAME = "plate-edge-close"

_SEV_CLASS = {"BLOCK": "sev-block", "WARN": "sev-warn", "NOTE": "sev-note"}

# (chart label, data directory, editorial tooltip note). The numbers are computed;
# only the one-line commentary is editorial. Chart order = chronological.
_AD_LOTS: tuple[tuple[str, str, str], ...] = (
    ("pilot", "lot3-ad", "Free-text forms, no closed vocabularies yet."),
    ("lot 4", "lot4-ads", "After the design change: closed vocabularies."),
    ("lot 6", "lot6-ads", "Single-record lots are noisy by nature."),
    ("lot 7", "lot7-ads", "The current machine."),
)


@dataclass(frozen=True)
class LotRow:
    label: str
    documents: int
    facts: int
    blanks: int
    note: str

    @property
    def rate(self) -> float:
        return self.blanks / (self.facts + self.blanks)


def _read_json(relative: str) -> Any:
    return json.loads((REPO_ROOT / relative).read_text())


def _load_lots() -> list[LotRow]:
    rows: list[LotRow] = []
    for label, directory, note in _AD_LOTS:
        merged = _read_json(f"data/facts/{directory}/merged.json")
        if "stats" in merged:
            stats = merged["stats"]
            row = LotRow(
                label, int(stats["documents"]), int(stats["facts"]), int(stats["blanks"]), note
            )
            stored = float(stats["divergence_rate"])
            if abs(row.rate - stored) > 0.0005:
                raise ValueError(
                    f"{directory}: stored divergence_rate {stored} disagrees "
                    f"with recomputed {row.rate:.4f}"
                )
        else:
            # The AD pilot predates the batch format: one document, flat lists.
            row = LotRow(label, 1, len(merged["facts"]), len(merged["blanks"]), note)
        rows.append(row)
    return rows


def _plural_records(n: int) -> str:
    return f"{n} record" if n == 1 else f"{n} records"


def _rule_bar_rows(
    rules: list[Rule], support: dict[str, Any], fixtures: frozenset[str]
) -> tuple[str, str]:
    severity = {r.rule_id: r.severity.value for r in rules}
    counts = {rid: int(entry["count"]) for rid, entry in support.items()}
    docs = {rid: list(entry["documents"]) for rid, entry in support.items()}
    peak = max(counts.values())
    # Real rules by support, the test fixture last whatever its count: it is
    # not an engineering fact and must not outrank one (audit 2026-09-02).
    order = sorted(counts, key=lambda rid: (rid in fixtures, -counts[rid], rid))
    bars: list[str] = []
    table: list[str] = []
    for rid in order:
        n, sev = counts[rid], severity[rid]
        prefix = "TEST FIXTURE · " if rid in fixtures else ""
        if n > 0:
            shown = sorted(docs[rid])[:7]
            tail = f" … and {n - len(shown)} more" if n > len(shown) else ""
            tip = (
                f"{prefix}{rid} · {n} AD{'s' if n != 1 else ''}|"
                f"{' · '.join(shown)}{tail}, each quoted in the repo (contiguity measured in data/facts/provenance.json)"
            )
            width = f"{n / peak * 86:.1f}"
            track = (
                f'<span class="fill" style="width:{width}%"></span>'
                f'<span class="rval num" style="left:calc({width}% + 8px)">{n}</span>'
            )
        else:
            tip = (
                f"{prefix}{rid} · 0 events|No event in the record speaks to this "
                "rule's quantity. The fusion refuses to inflate."
            )
            track = (
                '<span class="zero-stub"></span>'
                '<span class="rval num" style="left:12px; color:var(--muted)">0</span>'
            )
        bars.append(
            f'<div class="rrow rrow-hit" tabindex="0" data-tip="{escape(tip, quote=True)}">\n'
            f'            <span class="rid">{rid}</span>'
            f'<span class="sev {_SEV_CLASS[sev]}">{sev}</span>\n'
            f'            <span class="track">{track}</span>\n          </div>'
        )
        table.append(f"<tr><td>{prefix}{rid}</td><td>{sev}</td><td>{n}</td></tr>")
    return "\n          ".join(bars), "".join(table)


def _lot_fragments(lots: list[LotRow]) -> tuple[str, str, str]:
    peak = max(row.rate for row in lots)
    bars: list[str] = []
    axis: list[str] = []
    table: list[str] = []
    for row in lots:
        pct = f"{row.rate * 100:.1f}"
        height = f"{row.rate / peak * 100:.1f}"
        tip = (
            f"{row.label.capitalize()} · {_plural_records(row.documents)}|"
            f"{pct}% flagged blank. {row.note}"
        )
        bars.append(
            f'<div class="lot" tabindex="0" data-tip="{escape(tip, quote=True)}">'
            f'<span class="pv num">{pct}%</span>'
            f'<span class="bar" style="height:{height}%"></span></div>'
        )
        axis.append(f"<div>{row.label}<br>{_plural_records(row.documents)}</div>")
        table.append(f"<tr><td>{row.label}</td><td>{row.documents}</td><td>{pct}%</td></tr>")
    return "\n            ".join(bars), "".join(axis), "".join(table)


def _display_quote(excerpt: str) -> str:
    """Anchors mark elisions as ' [...] '; the page shows them as ellipses.
    Everything around them stays verbatim (pinned by test)."""
    return escape(excerpt.replace(" [...] ", " … "))


def _correction_values(spec: PartSpec, rules: list[Rule]) -> dict[str, str]:
    with tempfile.TemporaryDirectory() as tmp:
        tmpdir = Path(tmp)
        submitted = export_part(spec, tmpdir)
        before = evaluate(spec.context, measure_step_file(submitted), rules)
        result = correct_until_clean(spec, rules, tmpdir)
        after = evaluate(result.spec.context, list(result.proof), rules)
    if not before or after:
        raise ValueError(
            f"correction demo must go from some violations to zero; "
            f"got {len(before)} before and {len(after)} after"
        )
    diameters = {hole.diameter for hole in spec.holes}
    if len(diameters) != 1:
        raise ValueError("the drawing's diameter callout assumes one hole diameter")
    hole_d = diameters.pop()
    ratio_before = min(v.measured for v in before)
    ratio_after = next(
        m.value
        for m in result.proof
        if m.feature_id == "hole-1" and m.quantity == "edge_distance_over_diameter"
    )
    return {
        "VIOL_BEFORE": str(len(before)),
        "VIOL_AFTER": str(len(after)),
        "RATIO_BEFORE": f"{ratio_before:.3f}",
        "RATIO_AFTER": f"{ratio_after:.3f}",
        "OLD_EDGE_MM": f"{ratio_before * hole_d:.2f}",
        "OLD_RATIO": f"{ratio_before:.2f}",
        "NEW_EDGE_MM": f"{ratio_after * hole_d:.2f}",
        "NEW_RATIO": f"{ratio_after:.2f}",
        "HOLE_COUNT": str(len(spec.holes)),
        "HOLE_D": f"{hole_d:.2f}",
        "PART_LEN": f"{spec.length:.2f}",
        "PART_WID": f"{spec.width:.2f}",
        "PART_LEN_INT": f"{spec.length:g}",
        "PART_WID_INT": f"{spec.width:g}",
        "PART_NAME_UC": spec.name.upper(),
    }


def collect_values() -> dict[str, str]:
    """Compute every placeholder value from primary sources."""
    vault = _read_json("data/raw/vault.json")
    fusion = _read_json("data/facts/fusion-combined.json")
    gold = _read_json("data/facts/gold/conference-1.json")
    # The machine cross-check of the AD facts (2026-09-03). Kept apart from the
    # gold set on purpose: it never feeds the invention rate.
    machine = _read_json("data/facts/gold/conference-machine-1.json")
    plate_7050 = _read_json("data/facts/lot5-manual/7050_plate/merged.json")
    # Measured by scheinman.provenance, never claimed (audit 2026-09-02).
    provenance = _read_json("data/facts/provenance.json")
    rules = load_rules()
    lots = _load_lots()

    rate = len(gold["facts_wrong"]) / gold["facts_total"]
    if rate != gold["invention_rate"]:
        raise ValueError("gold set invention_rate disagrees with its own record")
    if rate != 0.0:
        raise ValueError("publication gate: the panel only renders at invention rate zero")

    # Production totals exclude the pilot: the pilot is the "before" point in
    # the by-lot chart, not part of the machine at scale.
    production = [row for row in lots if row.label != "pilot"]
    facts_total = sum(row.facts for row in production)
    blanks_total = sum(row.blanks for row in production)
    docs_total = sum(row.documents for row in production)
    overall_rate = blanks_total / (facts_total + blanks_total)
    latest = production[-1]

    r1 = next(r for r in rules if r.rule_id == "R-0001")
    if len(r1.event_anchors) != 2:
        raise ValueError("the rule card shows exactly two event anchors")
    # Prose-data couplings the template hardcodes (deep audit 2026-09-01):
    # "THE ONLY BLOCK" and "those two rules" must stay true or the build stops.
    blocks = [r.rule_id for r in rules if r.severity.value == "BLOCK"]
    if blocks != ["R-0001"]:
        raise ValueError(f"template prose says R-0001 is the only BLOCK; rules say {blocks}")
    zero_support = sorted(
        rid for rid, entry in fusion["support"].items() if int(entry["count"]) == 0
    )
    if len(zero_support) != 2:
        raise ValueError(
            f"template prose says two rules have zero events; the data says {zero_support}"
        )
    fixture_rules = frozenset(
        r.rule_id for r in rules if r.threshold_anchor.kind.value == "test_fixture"
    )
    fixture_note = (
        " ".join(
            f"{rid} is a synthetic test-fixture rule (it proves the machine on demo parts) "
            "and is never publishable as an engineering fact."
            for rid in sorted(fixture_rules)
        )
        if fixture_rules
        else ""
    )

    blank_pages = {fact["page"] for fact in plate_7050["facts"]}
    if len(blank_pages) != 1:
        raise ValueError("7050 plate facts must come from a single handbook page")
    blanks_7050 = plate_7050["blanks"]
    if [b["field_id"] for b in blanks_7050] != ["ftu_ST_A_ksi"]:
        raise ValueError(
            "the blank-example prose describes the short-transverse Ftu field; "
            "the data no longer matches it"
        )

    ad_count = len(list((REPO_ROOT / "data" / "raw" / "ads").glob("*.txt")))
    demo_spec = next(s for s in stage1_parts() if s.name == DEMO_PART_NAME)

    values: dict[str, str] = {
        "AS_OF": max(str(gold["date_adjudicated"]), str(fusion["date"])),
        "AD_COUNT": str(ad_count),
        "HANDBOOK_PAGES": f"{int(vault['handbook_pages']):,}",
        "FACTS_TOTAL": str(facts_total),
        "EXCERPTS_CHECKED": str(int(provenance["facts_checked"])),
        "EXCERPTS_FOUND": str(int(provenance["facts_found_contiguous"])),
        "EXCERPTS_DEVIATING": str(int(provenance["facts_deviating"])),
        "BLANKS_TOTAL": str(blanks_total),
        "DOCS_TOTAL": str(docs_total),
        "EVENTS_TOTAL": str(int(fusion["events_total"])),
        "OVERALL_BLANK_PCT": f"{overall_rate * 100:.1f}",
        "LATEST_BLANK_PCT": f"{latest.rate * 100:.1f}",
        "RULES_COUNT": str(len(rules)),
        "R1_COUNT": str(int(fusion["support"]["R-0001"]["count"])),
        "R2_COUNT": str(int(fusion["support"]["R-0002"]["count"])),
        "MACHINE_TOTAL": str(int(machine["facts_total"])),
        "MACHINE_WRONG": str(len(machine["facts_wrong"])),
        "MACHINE_CONTROLS": str(int(machine["controls_planted"])),
        "MACHINE_CONTROLS_CAUGHT": str(int(machine["controls_caught"])),
        "GOLD_TOTAL": str(int(gold["facts_total"])),
        "GOLD_RIGHT": str(int(gold["facts_total"]) - len(gold["facts_wrong"])),
        "GOLD_DATE": str(gold["date_adjudicated"]),
        "INVENTION_RATE": f"{rate:.1f}",
        "R1_QUANTITY": r1.quantity.replace("_over_", " / "),
        "R1_MIN": f"{r1.minimum:.1f}",
        "R1_THRESHOLD_QUOTE": _display_quote(r1.threshold_anchor.excerpt),
        "R1_EV1_QUOTE": _display_quote(r1.event_anchors[0].excerpt),
        "R1_EV2_QUOTE": _display_quote(r1.event_anchors[1].excerpt),
        "BLANK_AGREED": str(len(plate_7050["facts"])),
        "BLANK_FIELDS": str(len(plate_7050["facts"]) + len(blanks_7050)),
        "BLANK_PAGE": str(blank_pages.pop()),
    }
    values.update(_correction_values(demo_spec, rules))
    values["DRAWING_ARIA"] = (
        f"Dimensioned drawing of a {values['PART_LEN_INT']} by {values['PART_WID_INT']} "
        f"millimeter sheet. A fastener hole submitted {values['OLD_EDGE_MM']} millimeters "
        f"from the edge, rejected by rule R-0001, was recentered by the machine to "
        f"{values['NEW_EDGE_MM']} millimeters, which is {values['NEW_RATIO']} diameters. "
        "A revision cloud marks the corrected hole. A second hole is unchanged."
    )
    values["FIXTURE_NOTE"] = fixture_note

    rule_bars, rule_table = _rule_bar_rows(rules, fusion["support"], fixture_rules)
    lot_bars, lot_axis, lot_table = _lot_fragments(lots)
    values.update(
        {
            "RULE_BARS": rule_bars,
            "RULE_TABLE_ROWS": rule_table,
            "LOT_BARS": lot_bars,
            "LOT_AXIS": lot_axis,
            "LOT_TABLE_ROWS": lot_table,
        }
    )
    return values


def build_panel_html() -> str:
    """The page fragment: what the private artifact preview publishes."""
    return Template(TEMPLATE_PATH.read_text()).substitute(collect_values())


def render_document(fragment: str) -> str:
    """The standalone page: a complete HTML document, no quirks mode.

    The fragment opens with title/link/style; everything through the first
    closing style tag belongs in the head, the rest in the body."""
    cut = fragment.index("</style>") + len("</style>")
    return (
        '<!doctype html>\n<html lang="en">\n<head>\n<meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
        f"{fragment[:cut]}\n</head>\n<body>{fragment[cut:]}\n</body>\n</html>\n"
    )


def write_panel() -> Path:
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(render_document(build_panel_html()))
    return OUTPUT_PATH


if __name__ == "__main__":
    print(write_panel())
