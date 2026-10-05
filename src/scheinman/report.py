"""Render the inspection report, in English, every claim anchored."""

from __future__ import annotations

from pathlib import Path

from scheinman.correction import CorrectionResult
from scheinman.schemas import AnchorKind, Measurement, Rule, UsageContext, Violation

SEVERITY_ORDER = {"BLOCK": 0, "WARN": 1, "NOTE": 2}
_SEVERITY_ORDER = SEVERITY_ORDER


def rule_scopes(rules: list[Rule]) -> dict[str, str]:
    """What each rule is for, and how far this project stretches it."""
    return {r.rule_id: r.scope for r in rules}


def not_exercised_sentence(
    context: UsageContext, measurements: list[Measurement], rules: list[Rule]
) -> tuple[str, str, str]:
    """Which rules passed, which nothing on this part exercised, and which the
    declared context switched off.

    A rule only "passed" where a measurement of its quantity exists and the
    context applies; anything else is named for what it is instead of riding a
    blanket pass claim (deep audit 2026-09-01). Both the markdown report and the
    delivered PDF say this, so the division lives here and neither decides it.
    """
    from scheinman.verdict import applicable

    applicable_rules = [r for r in rules if applicable(r, context)]
    quantities = {m.quantity for m in measurements}
    passed = [r.rule_id for r in applicable_rules if r.quantity in quantities]
    silent = [r.rule_id for r in applicable_rules if r.quantity not in quantities]
    inapplicable = [r.rule_id for r in rules if not applicable(r, context)]
    return ", ".join(passed), ", ".join(silent), ", ".join(inapplicable)


def proof_sentence(result: CorrectionResult, rules: list[Rule]) -> str:
    """The claim the re-measurement backs, in one sentence with one owner."""
    rule_ids = ", ".join(r.rule_id for r in rules)
    return (
        f"The corrected file {result.step_path.name} was re-exported, re-measured by the "
        f"same measurer, and re-judged by the same rules ({rule_ids}) in "
        f"{result.rounds} correction round(s): zero WARN or BLOCK violations remain."
    )


def render_report(
    part_name: str,
    context: UsageContext,
    measurements: list[Measurement],
    violations: list[Violation],
    rules_evaluated: list[Rule],
) -> str:
    lines: list[str] = []
    lines.append(f"# Inspection report: {part_name}")
    lines.append("")
    lines.append(
        f"Declared context: material series {context.material_series}, "
        f"loading {context.loading.value}. A CAD file holds shape, never purpose; "
        "the context above was declared by the requester."
    )
    lines.append("")
    lines.append("## Measurements")
    lines.append("")
    for m in measurements:
        lines.append(f"- {m.feature_id}: {m.quantity} = {m.value:.3f} {m.unit} ({m.method})")
    lines.append("")
    lines.append("## Findings")
    lines.append("")
    passed, silent, inapplicable = not_exercised_sentence(context, measurements, rules_evaluated)
    if not violations:
        lines.append(f"No violations. Rules passed on measured values: {passed}.")
    scopes = rule_scopes(rules_evaluated)
    for v in sorted(violations, key=lambda v: (_SEVERITY_ORDER[v.severity.value], v.rule_id)):
        lines.append(f"### {v.severity.value}: rule {v.rule_id} at {v.feature_id}")
        lines.append("")
        lines.append(v.explanation)
        lines.append("")
        if scopes.get(v.rule_id):
            # What the source rule is for and how far this project stretches it
            # (audit 2026-09-02): the reader judges the stretch.
            lines.append(f"Scope: {scopes[v.rule_id]}")
            lines.append("")
        lines.append("Sources:")
        for a in v.anchors:
            fixture = (
                " [TEST FIXTURE - not a published engineering fact]"
                if (a.kind is AnchorKind.TEST_FIXTURE)
                else ""
            )
            lines.append(f'- {a.source} - {a.locator}{fixture}: "{a.excerpt}"')
        lines.append("")
    # Said with or without findings (owner's question, 2026-09-03): a rule the
    # declared context switched off, or one nothing on the part exercised, is
    # not a rule that passed.
    if silent:
        lines.append(
            f"Not exercised, because no measurement of their quantity exists on this part: "
            f"{silent}."
        )
    if inapplicable:
        lines.append(f"Not applicable to the declared context: {inapplicable}.")
    return "\n".join(lines)


def render_correction_report(
    part_name: str,
    context: UsageContext,
    before: list[Violation],
    result: CorrectionResult,
    rules_evaluated: list[Rule],
) -> str:
    """The fabrication-package report: what was wrong, what changed, and the
    re-measurement that proves the corrected file is clean."""
    lines: list[str] = []
    lines.append(f"# Correction report: {part_name}")
    lines.append("")
    lines.append(
        f"Declared context: material series {context.material_series}, "
        f"loading {context.loading.value}."
    )
    lines.append("")
    lines.append("## Violations found on the submitted part")
    lines.append("")
    scopes = rule_scopes(rules_evaluated)
    for v in sorted(before, key=lambda v: (_SEVERITY_ORDER[v.severity.value], v.rule_id)):
        lines.append(
            f"- {v.severity.value} {v.rule_id} at {v.feature_id}: measured "
            f"{v.measured:g} {v.unit}, required minimum {v.required_minimum:g} {v.unit}"
        )
        if scopes.get(v.rule_id):
            lines.append(f"  scope: {scopes[v.rule_id]}")
    lines.append("")
    lines.append("## Corrections applied (arithmetic on part parameters)")
    lines.append("")
    for c in result.corrections:
        lines.append(f"- rule {c.rule_id} ({c.quantity}): {c.action}")
    lines.append("")
    lines.append("## Proof by re-measurement")
    lines.append("")
    lines.append(proof_sentence(result, rules_evaluated))
    lines.append("")
    if result.recorded:
        # Guidance and fixtures are recorded, never enforced by moving metal.
        lines.append(
            "Findings recorded on the corrected part, not corrected (NOTE or test fixture):"
        )
        lines.append("")
        for v in sorted(result.recorded, key=lambda v: (v.rule_id, v.feature_id)):
            lines.append(
                f"- {v.severity.value} {v.rule_id} at {v.feature_id}: measured {v.measured:g} "
                f"{v.unit}, guidance minimum {v.required_minimum:g} {v.unit}"
            )
        lines.append("")
    for m in result.proof:
        lines.append(f"- {m.feature_id}: {m.quantity} = {m.value:.3f} {m.unit}")
    return "\n".join(lines)


def write_demo_packages(directory: Path) -> list[Path]:
    """Regenerate the demo fabrication packages (data/reports) from code.

    One-shot hand-run artifacts drift (deep audit 2026-09-01); this builder plus
    tests/test_reports_freshness.py keep them provably equal to what the current
    pipeline produces. Run: uv run python -m scheinman.report
    """
    import tempfile

    from scheinman.measure import measure_step_file
    from scheinman.parts import export_part, stage1_parts
    from scheinman.rules import publishable_rules
    from scheinman.verdict import evaluate

    # The demo packages show what a visitor gets: publishable rules only.
    rules = publishable_rules()
    directory.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    with tempfile.TemporaryDirectory() as tmp:
        for spec in stage1_parts():
            tmpdir = Path(tmp)
            step = export_part(spec, tmpdir)
            measurements = measure_step_file(step)
            before = evaluate(spec.context, measurements, rules)
            inspection = directory / f"{spec.name}.md"
            inspection.write_text(
                render_report(spec.name, spec.context, measurements, before, rules) + "\n"
            )
            written.append(inspection)
            if before:
                from scheinman.correction import correct_until_clean

                result = correct_until_clean(spec, rules, tmpdir)
                out = directory / f"{spec.name}-correction.md"
                out.write_text(
                    render_correction_report(spec.name, spec.context, before, result, rules) + "\n"
                )
                shipped = directory / result.step_path.name
                shipped.write_bytes(result.step_path.read_bytes())
                written.extend([out, shipped])
    return written


if __name__ == "__main__":
    for p in write_demo_packages(Path(__file__).resolve().parents[2] / "data" / "reports"):
        print(p)
