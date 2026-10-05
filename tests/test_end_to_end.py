"""End to end, honestly: generate part, export STEP, re-import, measure,
apply rules, compare against the planted answer key, render the report.

The stage-1 done criteria live here as assertions: every planted violation
found, zero false positives, every finding fully anchored in the report.
"""

from pathlib import Path

import pytest

from scheinman.measure import measure_step_file
from scheinman.parts import PartSpec, export_part, stage1_parts
from scheinman.report import render_report
from scheinman.rules import load_rules
from scheinman.schemas import AnchorKind, Severity
from scheinman.verdict import applicable, evaluate

SPECS = stage1_parts()


@pytest.fixture(scope="module")
def rules() -> list:  # type: ignore[type-arg]
    return load_rules()


@pytest.mark.parametrize("spec", SPECS, ids=[s.name for s in SPECS])
def test_planted_violations_all_found_and_nothing_else(
    spec: PartSpec,
    tmp_path: Path,
    rules: list,  # type: ignore[type-arg]
) -> None:
    step = export_part(spec, tmp_path)
    measurements = measure_step_file(step)
    violations = evaluate(spec.context, measurements, rules)
    found = {(v.rule_id, v.feature_id) for v in violations}
    assert found == spec.planted, (
        f"{spec.name}: expected exactly {sorted(spec.planted)}, got {sorted(found)}"
    )


@pytest.mark.parametrize("spec", SPECS, ids=[s.name for s in SPECS])
def test_report_every_finding_is_anchored(
    spec: PartSpec,
    tmp_path: Path,
    rules: list,  # type: ignore[type-arg]
) -> None:
    step = export_part(spec, tmp_path)
    measurements = measure_step_file(step)
    violations = evaluate(spec.context, measurements, rules)
    evaluated = [r for r in rules if applicable(r, spec.context)]
    report = render_report(spec.name, spec.context, measurements, violations, evaluated)

    assert report.count("Sources:") == len(violations)
    for v in violations:
        assert v.explanation in report
        for anchor in v.anchors:
            assert anchor.excerpt in report, "every claim must show its anchor verbatim"
        if any(a.kind is AnchorKind.TEST_FIXTURE for a in v.anchors):
            assert "TEST FIXTURE - not a published engineering fact" in report
    if not violations:
        assert "No violations" in report
        assert all(r.rule_id in report for r in evaluated)


def test_block_fires_only_with_the_documented_combination(rules: list) -> None:  # type: ignore[type-arg]
    blocks = [r for r in rules if r.severity is Severity.BLOCK]
    assert len(blocks) == 1, "stage 1 plants exactly one BLOCK rule (pyramid by construction)"
    # Rule base v2: R-0001 carries two real failure events (ADs E7-9396 and 00-4568).
    assert len(blocks[0].event_anchors) == 2


def test_measurer_sees_clean_part_features(tmp_path: Path) -> None:
    clean = SPECS[0]
    measurements = measure_step_file(export_part(clean, tmp_path))
    by_quantity = {m.quantity for m in measurements}
    assert {
        "thickness_mm",
        "hole_diameter_mm",
        "edge_distance_over_diameter",
        "hole_pitch_over_diameter",
        "corner_fillet_radius_mm",
    } <= by_quantity
    holes = [m for m in measurements if m.quantity == "hole_diameter_mm"]
    assert len(holes) == 3
    for m in measurements:
        if m.quantity == "hole_diameter_mm":
            assert abs(m.value - 6.5) < 1e-3
        if m.quantity == "corner_fillet_radius_mm":
            assert abs(m.value - 3.0) < 1e-3
