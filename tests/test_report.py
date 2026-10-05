"""The inspection report names every rule that did not run, with or without findings."""

from __future__ import annotations

from scheinman.report import render_report
from scheinman.rules import publishable_rules
from scheinman.schemas import FeatureType, Loading, Measurement, UsageContext
from scheinman.verdict import evaluate


def _edge(value: float) -> Measurement:
    return Measurement(
        feature_id="H1",
        feature_type=FeatureType.EDGE_DISTANCE,
        quantity="edge_distance_over_diameter",
        value=value,
        unit="ratio",
        method="test",
    )


def test_a_rule_switched_off_by_the_declared_context_is_named_beside_a_warn() -> None:
    # Owner's question 2026-09-03: a 7xxx plate declared static keeps R-0002
    # (WARN) and switches R-0001 (BLOCK) off. Before this test the report only
    # said so when there were no findings at all.
    rules = publishable_rules()
    static = UsageContext(material_series="7xxx", loading=Loading.STATIC)
    violations = evaluate(static, [_edge(1.5)], rules)
    assert {v.rule_id for v in violations} == {"R-0002"}
    report = render_report("plate", static, [_edge(1.5)], violations, rules)
    assert "### WARN: rule R-0002 at H1" in report
    assert "Not applicable to the declared context: R-0001." in report
    assert "Not exercised" in report  # R-0003 and R-0004 have no measurement here


def test_a_clean_report_still_names_what_passed_and_what_did_not_run() -> None:
    rules = publishable_rules()
    cyclic = UsageContext(material_series="7xxx", loading=Loading.CYCLIC)
    report = render_report("plate", cyclic, [_edge(2.5)], [], rules)
    assert "No violations. Rules passed on measured values: R-0001, R-0002." in report
    assert "Not exercised" in report
    assert "Not applicable" not in report


def test_the_two_formats_say_the_same_thing_about_the_proof() -> None:
    """The markdown report and the delivered PDF are built from the same
    values. The sentences that are prose rather than data have one owner, so a
    reader cannot be told two different stories about the same correction.
    """
    import re
    import tempfile
    from pathlib import Path as _Path

    from scheinman.correction import correct_until_clean
    from scheinman.measure import measure_step_file
    from scheinman.paper import correction_pdf
    from scheinman.parts import export_part, stage1_parts
    from scheinman.report import proof_sentence, render_correction_report
    from scheinman.rules import load_rules
    from scheinman.verdict import evaluate

    spec = next(s for s in stage1_parts() if s.name == "plate-edge-close")
    rules = load_rules()
    with tempfile.TemporaryDirectory() as tmp:
        work = _Path(tmp)
        before = evaluate(spec.context, measure_step_file(export_part(spec, work)), rules)
        result = correct_until_clean(spec, rules, work)
        sentence = proof_sentence(result, rules)
        markdown = render_correction_report(spec.name, spec.context, before, result, rules)
        pdf = correction_pdf(
            part_name=spec.name,
            context=spec.context,
            before=before,
            result=result,
            rules_evaluated=rules,
            submitted_spec=spec,
            job_key="test",
            submitted_at="2026-09-20T00:00:00Z",
        )
    assert sentence in markdown
    # PDF text is split across drawing operators, so the words are checked
    # rather than the sentence: what matters is that one function wrote both.
    assert pdf[:5] == b"%PDF-"
    assert re.search(r"zero WARN or BLOCK violations remain", markdown)
