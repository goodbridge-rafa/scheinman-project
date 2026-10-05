"""Correction is arithmetic on parameters, and only re-measurement proves it.

These tests run the full loop on the stage-1 parts: the planted violations
must exist before, the corrected part must measure clean after, and a clean
part must pass through untouched.
"""

from pathlib import Path

import pytest

from scheinman.correction import MARGIN, CorrectionRefused, correct_spec, correct_until_clean
from scheinman.measure import measure_step_file
from scheinman.parts import export_part, stage1_parts
from scheinman.rules import load_rules
from scheinman.verdict import evaluate

CLEAN, EDGE_CLOSE, TIGHT_THIN = stage1_parts()


def test_clean_part_passes_through_untouched(tmp_path: Path) -> None:
    result = correct_until_clean(CLEAN, load_rules(), tmp_path)
    assert result.rounds == 0
    assert result.corrections == ()
    assert result.spec == CLEAN


def test_edge_violation_is_corrected_and_proven_by_remeasurement(tmp_path: Path) -> None:
    rules = load_rules()
    before = evaluate(
        EDGE_CLOSE.context, measure_step_file(export_part(EDGE_CLOSE, tmp_path)), rules
    )
    assert {(v.rule_id, v.feature_id) for v in before} >= EDGE_CLOSE.planted
    result = correct_until_clean(EDGE_CLOSE, rules, tmp_path)
    assert result.rounds >= 1
    assert {c.rule_id for c in result.corrections} >= {"R-0001", "R-0002"}
    # The proof is the final measurement of the final file, judged by the same code.
    assert evaluate(result.spec.context, list(result.proof), rules) == []
    assert evaluate(result.spec.context, measure_step_file(result.step_path), rules) == []
    # The offending hole was moved exactly to the demanded distance, nothing else.
    moved = min(result.spec.holes, key=lambda h: (h.x, h.y))
    req = 2.0 * MARGIN * moved.diameter
    assert moved.x == pytest.approx(req)
    assert moved.y == pytest.approx(req)
    assert result.spec.thickness == EDGE_CLOSE.thickness


def test_pitch_is_corrected_and_the_fixture_note_is_recorded_not_enforced(tmp_path: Path) -> None:
    # Audit 2026-09-02: the test-fixture rule R-0005 used to thicken
    # the delivered plate. A NOTE, and any fixture, is recorded, never corrected.
    rules = load_rules()
    result = correct_until_clean(TIGHT_THIN, rules, tmp_path)
    assert {c.rule_id for c in result.corrections} == {"R-0003"}
    remaining = evaluate(result.spec.context, list(result.proof), rules)
    assert {(v.rule_id, v.severity.value) for v in remaining} == {("R-0005", "NOTE")}
    assert {(v.rule_id, v.feature_id) for v in result.recorded} == {("R-0005", "part")}
    assert result.spec.thickness == TIGHT_THIN.thickness, "metal is never moved for a NOTE"
    a, b = sorted(result.spec.holes, key=lambda h: (h.x, h.y))
    want_pitch = 3.0 * MARGIN * (a.diameter + b.diameter) / 2
    assert b.x - a.x == pytest.approx(want_pitch)
    # Only one hole moves (the one with more room to the boundary), so the
    # anchor hole stays exactly where the designer put it.
    assert a.x == pytest.approx(40.0)


def test_correction_report_carries_before_after_and_proof(tmp_path: Path) -> None:
    from scheinman.report import render_correction_report

    rules = load_rules()
    before = evaluate(
        EDGE_CLOSE.context, measure_step_file(export_part(EDGE_CLOSE, tmp_path)), rules
    )
    result = correct_until_clean(EDGE_CLOSE, rules, tmp_path)
    report = render_correction_report(EDGE_CLOSE.name, EDGE_CLOSE.context, before, result, rules)
    assert "BLOCK R-0001 at hole-1" in report
    assert "moved hole-1 center" in report
    assert "zero WARN or BLOCK violations remain" in report
    assert "Proof by re-measurement" in report


def test_too_small_plate_is_refused_not_mutilated(tmp_path: Path) -> None:
    # Audit 2026-08-30: on a 10 mm plate the edge fix pushed the hole center to
    # x = -2.24 (outside the part), the hole vanished from measurement and the
    # loop declared the part proven clean. The corrector must refuse instead.
    from scheinman.parts import Hole, PartSpec

    tiny = PartSpec(
        name="tiny",
        length=10,
        width=60,
        thickness=2,
        holes=(Hole(5, 30, 6),),
        context=CLEAN.context,
    )
    with pytest.raises(CorrectionRefused, match="too small"):
        correct_until_clean(tiny, load_rules(), tmp_path)


def test_edge_pitch_fight_converges(tmp_path: Path) -> None:
    # Audit 2026-08-30: edge and pitch fixes pull the same hole in opposite
    # directions and the error halves per round; the old 4-round ceiling raised
    # RuntimeError on a perfectly correctable part.
    from scheinman.parts import Hole, PartSpec

    fight = PartSpec(
        name="fight",
        length=100,
        width=60,
        thickness=2,
        holes=(Hole(10, 30, 6), Hole(20, 30, 6)),
        context=CLEAN.context,
    )
    rules = load_rules()
    result = correct_until_clean(fight, rules, tmp_path)
    assert evaluate(result.spec.context, list(result.proof), rules) == []


def test_null_move_is_recorded_honestly_not_as_movement(tmp_path: Path) -> None:
    # R-0001 and R-0002 demand the same move on the same hole; the second record
    # must not claim a movement from a position to the same position.
    result = correct_until_clean(EDGE_CLOSE, load_rules(), tmp_path)
    by_rule = {c.rule_id: c.action for c in result.corrections}
    assert "moved hole-1 center" in by_rule["R-0001"]
    assert "no additional change" in by_rule["R-0002"]
    assert "12.24) to (12.24" not in by_rule["R-0002"]


def test_corrected_package_file_carries_the_corrected_name(tmp_path: Path) -> None:
    result = correct_until_clean(EDGE_CLOSE, load_rules(), tmp_path)
    assert result.step_path.name == "plate-edge-close-corrected.step"
    assert result.step_path.exists()


def test_unknown_quantity_refuses_instead_of_guessing() -> None:
    from scheinman.schemas import Anchor, AnchorKind, Severity, Violation

    rule = load_rules()[0].model_copy(update={"quantity": "warp_factor"})
    measured = Anchor(
        kind=AnchorKind.SYSTEM_MEASUREMENT, source="engine", locator="x", excerpt="v = 1"
    )
    fake = Violation(
        rule_id=rule.rule_id,
        feature_id="hole-1",
        severity=Severity.WARN,
        measured=1.0,
        required_minimum=2.0,
        unit="ratio",
        explanation="x",
        anchors=(rule.threshold_anchor, measured),
    )
    with pytest.raises(CorrectionRefused, match="warp_factor"):
        correct_spec(EDGE_CLOSE, [fake], [rule])


def test_filleted_corner_edge_violation_is_corrected_not_stalled(tmp_path: Path) -> None:
    # Deep audit 2026-09-01: the corrector modeled the boundary as the four
    # straight edges while the measurer measures to the filleted outline, so a
    # hole violating only near a rounded corner got a no-op "correction" and
    # the loop burned every round before refusing a perfectly fixable part.
    from scheinman.parts import Hole, PartSpec
    from scheinman.verdict import evaluate

    spec = PartSpec(
        name="fillet-corner",
        length=100,
        width=60,
        thickness=2,
        holes=(Hole(12.5, 12.5, 6),),
        context=CLEAN.context,
        corner_fillet_radius=15,
    )
    rules = load_rules()
    result = correct_until_clean(spec, rules, tmp_path)
    assert evaluate(result.spec.context, list(result.proof), rules) == []
    assert result.corrections, "the violation demands a real move, not a no-op"


def test_pitch_spread_refuses_before_pushing_a_hole_wall_off_plate(tmp_path: Path) -> None:
    # Deep audit 2026-09-01: the guard only kept the moved CENTER inside the
    # plate, so the wall could cross the edge and the run died one round later
    # inside the measurer instead of refusing honestly here.
    from scheinman.parts import Hole, PartSpec

    spec = PartSpec(
        name="spread-overflow",
        length=33,
        width=30,
        thickness=1.8,
        holes=(Hole(12.3, 15, 6), Hole(20.5, 15, 6)),
        context=CLEAN.context,
    )
    with pytest.raises(CorrectionRefused, match="refusing correction|too small"):
        correct_until_clean(spec, load_rules(), tmp_path)


def test_sorted_holes_mirror_the_measurer_frame_rounding() -> None:
    # Deep audit 2026-09-01: spec-frame rounding disagreed with the measurer's
    # centered-frame rounding on plates whose half-dimensions are not multiples
    # of 0.1 mm, so near-tie holes could swap names between the two modules.
    from scheinman.correction import _sorted_holes
    from scheinman.parts import Hole, PartSpec

    spec = PartSpec(
        name="near-tie",
        length=99.5,
        width=60,
        thickness=2,
        holes=(Hole(10.01, 20, 3), Hole(10.06, 10, 3)),
        context=CLEAN.context,
    )
    measured_frame = sorted(
        spec.holes,
        key=lambda h: (round(h.x - spec.length / 2, 1), round(h.y - spec.width / 2, 1)),
    )
    assert _sorted_holes(spec) == measured_frame
