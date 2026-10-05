"""Correction: arithmetic on the part's parameters, proven by re-measurement.

The corrector never edits the STEP file. It recomputes the violating
parameters so every broken rule's minimum is met with one small deterministic
margin, rebuilds the part, and the same measurer plus the same verdict must
come back empty. The proof is the re-measurement, never the intent.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, replace
from pathlib import Path

from scheinman.measure import measure_step_file
from scheinman.parts import Hole, PartSpec, export_part
from scheinman.schemas import AnchorKind, Measurement, Rule, Severity, Violation
from scheinman.verdict import evaluate

# 2% above the rule minimum: a project margin so the corrected value re-measures
# clearly above the line. No source states a margin, so every correction says so.
MARGIN = 1.02
MARGIN_NOTE = "the minimum plus the project's 2% margin"


@dataclass(frozen=True)
class Correction:
    """One parameter change, tied to the violation that demanded it."""

    rule_id: str
    feature_id: str
    quantity: str
    action: str  # human sentence: what changed, from -> to


class CorrectionRefused(RuntimeError):
    """The corrector declines, on purpose, and says why.

    Every deliberate refusal raises this and nothing else, so the job can
    report it as UNCORRECTED with the sentence intact, while any OTHER error
    (a kernel failure, a bug) propagates, fails the run, and reaches the
    visitor as "the engine did not finish" instead of being dressed up as a
    verdict about the part (audit 2026-09-02).
    """


@dataclass(frozen=True)
class CorrectionResult:
    spec: PartSpec
    corrections: tuple[Correction, ...]
    proof: tuple[Measurement, ...]  # the re-measurement of the final part
    step_path: Path  # the exported file those measurements came from
    rounds: int
    # NOTE findings and test-fixture findings that remain on the corrected
    # part: recorded, never corrected (audit 2026-09-02).
    recorded: tuple[Violation, ...] = ()


def _sorted_holes(spec: PartSpec) -> list[Hole]:
    """The measurer names holes hole-1..n sorted by rounded (x, y) in the frame
    the STEP export lives in (centred for generated parts, the file's own for
    submitted ones); mirror that frame and rounding exactly, or near-ties would
    make the corrector move the wrong hole (audits 2026-08-30, 2026-09-01,
    2026-09-02)."""
    ox, oy, _ = spec.frame_origin
    return sorted(spec.holes, key=lambda h: (round(h.x + ox, 1), round(h.y + oy, 1)))


def _boundary_distance(spec: PartSpec, x: float, y: float) -> float:
    """Distance from an interior point to the top-face outline, fillet arcs
    included — the same boundary the measurer measures to."""
    d = min(x, y, spec.length - x, spec.width - y)
    r = spec.corner_fillet_radius
    if r > 0:
        for cx, cy, in_quadrant in (
            (r, r, x < r and y < r),
            (spec.length - r, r, x > spec.length - r and y < r),
            (r, spec.width - r, x < r and y > spec.width - r),
            (spec.length - r, spec.width - r, x > spec.length - r and y > spec.width - r),
        ):
            if in_quadrant:
                d = min(d, r - math.dist((x, y), (cx, cy)))
    return d


def _clear_of_fillets(spec: PartSpec, x: float, y: float, req: float) -> tuple[float, float]:
    """Move a point out of any filleted corner it violates. Only reachable when
    req < fillet radius: with req >= radius the straight-edge clamp already
    keeps the point outside every corner quadrant."""
    r = spec.corner_fillet_radius
    for cx, cy in (
        (r, r),
        (spec.length - r, r),
        (r, spec.width - r),
        (spec.length - r, spec.width - r),
    ):
        in_quadrant = (x < r if cx == r else x > cx) and (y < r if cy == r else y > cy)
        if not in_quadrant or r - math.dist((x, y), (cx, cy)) >= req:
            continue
        dx, dy = x - cx, y - cy
        norm = math.hypot(dx, dy)
        if norm == 0:
            corner = (0 if cx == r else spec.length, 0 if cy == r else spec.width)
            dx, dy = corner[0] - cx, corner[1] - cy
            norm = math.hypot(dx, dy)
        x = cx + dx / norm * (r - req)
        y = cy + dy / norm * (r - req)
    return x, y


def _hole_index(feature_id: str) -> int:
    return int(feature_id.removeprefix("hole-")) - 1


def correct_spec(
    spec: PartSpec, violations: list[Violation], rules: list[Rule]
) -> tuple[PartSpec, list[Correction]]:
    """One arithmetic pass: every violation gets its parameter fix."""
    by_rule = {r.rule_id: r for r in rules}
    holes = _sorted_holes(spec)
    thickness = spec.thickness
    fillet_radius = spec.corner_fillet_radius
    corrections: list[Correction] = []
    moved_this_pass: set[str] = set()
    for v in violations:
        rule = by_rule[v.rule_id]
        target = rule.minimum * MARGIN
        if rule.quantity == "edge_distance_over_diameter":
            i = _hole_index(v.feature_id)
            hole = holes[i]
            req = target * hole.diameter
            if 2 * req > spec.length or 2 * req > spec.width:
                # Audit 2026-08-30: the clamp used to push the center outside a
                # too-narrow plate, destroying the hole; refuse instead.
                raise CorrectionRefused(
                    f"{spec.name}: plate too small for the required edge distance of "
                    f"{req:g} mm on each side of {v.feature_id}; refusing correction"
                )
            new_x = min(max(hole.x, req), spec.length - req)
            new_y = min(max(hole.y, req), spec.width - req)
            if spec.corner_fillet_radius > 0 and req < spec.corner_fillet_radius:
                new_x, new_y = _clear_of_fillets(spec, new_x, new_y, req)
            if _boundary_distance(spec, new_x, new_y) + 1e-9 < req:
                raise CorrectionRefused(
                    f"{spec.name}: no position reaches {req:g} mm from the filleted "
                    f"boundary for {v.feature_id}; refusing correction"
                )
            if (new_x, new_y) == (hole.x, hole.y):
                if v.feature_id not in moved_this_pass:
                    # Deep audit 2026-09-01: this used to be reported as an
                    # "earlier correction" that never happened.
                    raise CorrectionRefused(
                        f"{spec.name}: the corrector computes {v.feature_id} already at "
                        f"boundary distance >= {req:g} mm yet the measurement reported a "
                        "violation; measurer and corrector disagree — refusing"
                    )
                action = (
                    f"{v.feature_id} already repositioned by an earlier correction in "
                    "this pass; no additional change"
                )
            else:
                moved_this_pass.add(v.feature_id)
                holes[i] = replace(hole, x=new_x, y=new_y)
                action = (
                    f"moved {v.feature_id} center from ({hole.x:g}, {hole.y:g}) to "
                    f"({new_x:g}, {new_y:g}) mm so its edge distance reaches "
                    f"{req:g} mm ({target:g} diameters: {MARGIN_NOTE})"
                )
        elif rule.quantity == "hole_pitch_over_diameter":
            ia, ib = (_hole_index(p) for p in v.feature_id.split("+"))
            a, b = holes[ia], holes[ib]
            pitch = math.dist((a.x, a.y), (b.x, b.y))
            if pitch == 0:
                raise CorrectionRefused(f"{v.feature_id}: coincident holes cannot be spread")
            want = target * (a.diameter + b.diameter) / 2
            if pitch >= want:
                action = (
                    f"{v.feature_id} pitch already adequate after an earlier correction "
                    "in this pass; no additional change"
                )
            else:
                # Move only the hole with more room to the plate boundary: a
                # symmetric spread tugs against the edge fix on the same hole
                # and converges by halving (audit 2026-08-30); moving the freer
                # hole ends the fight in one pass.
                def _slack(h: Hole) -> float:
                    return min(h.x, spec.length - h.x, h.y, spec.width - h.y)

                anchor_i, mover_i = (ia, ib) if _slack(b) >= _slack(a) else (ib, ia)
                anchor, mover = holes[anchor_i], holes[mover_i]
                ux, uy = (mover.x - anchor.x) / pitch, (mover.y - anchor.y) / pitch
                moved = replace(mover, x=anchor.x + ux * want, y=anchor.y + uy * want)
                # The wall, not just the center, must stay inside the boundary:
                # a center barely inside used to send the run into the measurer's
                # refusal one round later (deep audit 2026-09-01).
                if _boundary_distance(spec, moved.x, moved.y) <= moved.diameter / 2:
                    raise CorrectionRefused(
                        f"{spec.name}: plate too small to spread {v.feature_id} to "
                        f"{want:g} mm pitch; refusing correction"
                    )
                holes[mover_i] = moved
                action = (
                    f"moved one hole of {v.feature_id} away from the other, raising the "
                    f"pitch from {pitch:g} mm to {want:g} mm ({target:g} diameters: {MARGIN_NOTE})"
                )
        elif rule.quantity == "thickness_mm":
            new_thickness = max(thickness, target)
            action = f"raised thickness from {thickness:g} mm to {new_thickness:g} mm"
            thickness = new_thickness
        elif rule.quantity == "hole_diameter_over_thickness":
            i = _hole_index(v.feature_id)
            hole = holes[i]
            new_d = max(hole.diameter, target * thickness)
            holes[i] = replace(hole, diameter=new_d)
            action = f"enlarged {v.feature_id} diameter from {hole.diameter:g} mm to {new_d:g} mm"
        elif rule.quantity == "corner_fillet_radius_mm":
            new_r = max(fillet_radius, target)
            action = f"raised corner fillet radius from {fillet_radius:g} mm to {new_r:g} mm"
            fillet_radius = new_r
        else:
            raise CorrectionRefused(f"no correction is defined for quantity {rule.quantity!r}")
        corrections.append(
            Correction(
                rule_id=v.rule_id,
                feature_id=v.feature_id,
                quantity=rule.quantity,
                action=action,
            )
        )
    corrected = replace(
        spec, holes=tuple(holes), thickness=thickness, corner_fillet_radius=fillet_radius
    )
    return corrected, corrections


def correctable(violation: Violation, by_rule: dict[str, Rule]) -> bool:
    """Only a canonical WARN or BLOCK finding may change the delivered geometry.

    A NOTE is guidance recorded in the report, never enforced by moving metal,
    and a test fixture is not an engineering fact at all: before 2026-09-02 the
    fixture rule R-0005 would have thickened a visitor's plate in the delivered
    file (audit 2026-09-02).
    """
    rule = by_rule[violation.rule_id]
    if rule.threshold_anchor.kind is AnchorKind.TEST_FIXTURE:
        return False
    return violation.severity in (Severity.WARN, Severity.BLOCK)


def correct_until_clean(
    spec: PartSpec, rules: list[Rule], directory: Path, max_rounds: int = 8
) -> CorrectionResult:
    """Export, measure, judge; fix and repeat until the verdict is empty.

    The loop exists because fixes can interact (raising thickness moves the
    diameter-over-thickness ratio, edge and pitch fixes pull the same hole and
    converge by halving, which is why the ceiling is 8 rounds); each round is
    proven by a fresh export and a fresh measurement, and a part that will not
    converge raises instead of being declared done.
    """
    current = spec
    by_rule = {r.rule_id: r for r in rules}
    all_corrections: list[Correction] = []
    for round_number in range(max_rounds + 1):
        path = export_part(current, directory)
        measurements = measure_step_file(path)
        found = evaluate(current.context, measurements, rules)
        violations = [v for v in found if correctable(v, by_rule)]
        recorded = tuple(v for v in found if not correctable(v, by_rule))
        if not violations:
            measured_holes = sum(1 for m in measurements if m.quantity == "hole_diameter_mm")
            if measured_holes != len(current.holes):
                raise CorrectionRefused(
                    f"{spec.name}: corrected part shows {measured_holes} holes where the "
                    f"spec has {len(current.holes)}; refusing to declare it corrected"
                )
            if all_corrections:
                # The delivered file carries the corrected name, so the proof
                # line in the report points at the artifact that actually ships.
                corrected = path.with_name(f"{spec.name}-corrected.step")
                corrected.write_bytes(path.read_bytes())
                path = corrected
            return CorrectionResult(
                spec=current,
                corrections=tuple(all_corrections),
                proof=tuple(measurements),
                step_path=path,
                rounds=round_number,
                recorded=recorded,
            )
        current, corrections = correct_spec(current, violations, rules)
        all_corrections.extend(corrections)
    raise CorrectionRefused(
        f"{spec.name}: still not clean after {max_rounds} correction rounds; "
        "refusing to declare it corrected"
    )
