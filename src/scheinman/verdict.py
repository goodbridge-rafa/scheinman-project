"""The verdict: arithmetic over measurements, never model opinion."""

from __future__ import annotations

from scheinman.schemas import Loading, Measurement, Rule, UsageContext, Violation

# The comparison has a resolution, written down once (audit 2026-09-02).
# A measured value that sits on the minimum to within one part in a million is
# ON the minimum: the kernel's arithmetic is not exact, and "measured 3.000,
# required 3.000, violation" is a lie the reader cannot check. Registered in
# ecosystem/CONTRACTS.md as the measurement resolution.
RESOLUTION = 1e-6


def below_minimum(value: float, minimum: float) -> bool:
    """True when the value is short of the minimum by more than the resolution."""
    return value < minimum - RESOLUTION * max(1.0, abs(minimum))


def applicable(rule: Rule, context: UsageContext) -> bool:
    material_ok = (
        "any" in rule.applies_to_material_series
        or context.material_series in rule.applies_to_material_series
    )
    loading_ok = rule.applies_to_loading in (Loading.ANY, context.loading)
    return material_ok and loading_ok


def evaluate(
    context: UsageContext, measurements: list[Measurement], rules: list[Rule]
) -> list[Violation]:
    violations: list[Violation] = []
    for rule in rules:
        if not applicable(rule, context):
            continue
        for m in measurements:
            if m.quantity != rule.quantity:
                continue
            if m.unit != rule.unit:
                # A rule in inches judged against millimetres would be silently
                # wrong in both directions; refuse instead (audit 2026-09-02).
                raise ValueError(
                    f"{rule.rule_id} states its minimum in {rule.unit!r} but "
                    f"{m.feature_id} {m.quantity} was measured in {m.unit!r}; "
                    "refusing to compare quantities in different units"
                )
            if not below_minimum(m.value, rule.minimum):
                continue
            anchors = [rule.threshold_anchor, *rule.event_anchors, m.as_anchor()]
            violations.append(
                Violation(
                    rule_id=rule.rule_id,
                    feature_id=m.feature_id,
                    severity=rule.severity,
                    measured=round(m.value, 3),
                    required_minimum=rule.minimum,
                    unit=rule.unit,
                    explanation=(
                        f"{m.feature_id}: measured {rule.quantity} is {m.value:.3f} {m.unit}, "
                        f"below the required minimum of {rule.minimum:g} {rule.unit}. "
                        f"{rule.risk}"
                    ),
                    anchors=tuple(anchors),
                )
            )
    return violations
