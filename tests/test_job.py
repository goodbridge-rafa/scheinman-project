"""The job runner is the whole product for one part: measure, judge, correct, prove.

Everything the public counter will show comes out of run_job, so these tests
pin the four possible endings, the refusal to correct a part it cannot rebuild
faithfully, and the promise that resubmitting the same part does not run twice.
"""

from __future__ import annotations

import json
from io import BytesIO
from pathlib import Path

import pytest

from scheinman.job import (
    RESULT_FILENAME,
    JobResult,
    JobStatus,
    _rebuild_disagreement,
    job_key,
    main,
    run_job,
)
from scheinman.measure import measure_step_file
from scheinman.parts import PartSpec, export_part, stage1_parts
from scheinman.rules import load_rules
from scheinman.schemas import FeatureType, Loading, Measurement, UsageContext
from scheinman.verdict import evaluate

CYCLIC_7XXX = UsageContext(material_series="7xxx", loading=Loading.CYCLIC)


def _demo(name: str) -> PartSpec:
    return next(s for s in stage1_parts() if s.name == name)


def _run(spec: PartSpec, tmp_path: Path, folder: str = "out") -> tuple[JobResult, Path]:
    step = export_part(spec, tmp_path)
    return run_job(step, spec.context, tmp_path / folder, part_name=spec.name), step


def test_clean_part_is_reported_clean_with_no_corrected_file(tmp_path: Path) -> None:
    result, _ = _run(_demo("plate-clean"), tmp_path)
    assert result.status is JobStatus.CLEAN
    assert result.violations == ()
    assert "corrected_step" not in result.files
    assert (tmp_path / "out" / result.files["inspection_report"]).exists()


def test_violating_part_is_corrected_and_the_delivered_file_measures_clean(
    tmp_path: Path,
) -> None:
    result, _ = _run(_demo("plate-edge-close"), tmp_path)
    assert result.status is JobStatus.CORRECTED
    assert result.violations and result.corrections
    corrected = tmp_path / "out" / result.files["corrected_step"]
    # The proof is re-measurement of the file that actually ships, not intent.
    assert evaluate(CYCLIC_7XXX, measure_step_file(corrected), load_rules()) == []


def test_every_violation_carries_a_quotable_source_for_the_dashboard(tmp_path: Path) -> None:
    result, _ = _run(_demo("plate-edge-close"), tmp_path)
    for violation in result.violations:
        non_measurement = [a for a in violation.anchors if a.kind.value != "system_measurement"]
        assert non_measurement, f"{violation.rule_id} has nothing to cite on screen"
        assert all(a.excerpt.strip() for a in non_measurement)


def test_unmeasurable_part_is_refused_with_a_reason_and_no_verdict(tmp_path: Path) -> None:
    from build123d import Box, Cylinder, Pos, Rot, export_step

    solid = Box(100, 60, 2) - Pos(0, 0, 0) * Rot(90, 0, 0) * Cylinder(0.5, 200)
    step = tmp_path / "sideways.step"
    export_step(solid, str(step))
    result = run_job(step, CYCLIC_7XXX, tmp_path / "out", part_name="sideways")
    assert result.status is JobStatus.REFUSED
    assert "not vertical" in (result.reason or "")
    assert result.measurements == () and result.violations == ()
    assert "inspection_report" not in result.files


def test_part_that_cannot_be_rebuilt_is_reported_but_never_corrected(tmp_path: Path) -> None:
    # A notch out of one side: measurable (the rules still apply), but no
    # parameter set describes that outline, so correcting would correct a
    # different part. The report is still delivered.
    from build123d import Box, Cylinder, Pos, export_step

    solid = Box(100, 60, 2) - Pos(50, 30, 0) * Box(20, 20, 10) - Pos(-40, -22, 0) * Cylinder(3, 10)
    step = tmp_path / "notched.step"
    export_step(solid, str(step))
    result = run_job(step, CYCLIC_7XXX, tmp_path / "out", part_name="notched")
    assert result.status is JobStatus.UNCORRECTED
    assert result.violations
    assert "not a plain plate" in (result.reason or "")
    assert "corrected_step" not in result.files
    assert (tmp_path / "out" / result.files["inspection_report"]).exists()


def test_resubmitting_the_same_part_returns_the_finished_job_instead_of_running_again(
    tmp_path: Path,
) -> None:
    spec = _demo("plate-edge-close")
    first, step = _run(spec, tmp_path)
    report = tmp_path / "out" / first.files["inspection_report"]
    report.write_bytes(b"SENTINEL")
    second = run_job(step, spec.context, tmp_path / "out", part_name=spec.name)
    assert second == first
    # Untouched: a second run would have rewritten the report.
    assert report.read_bytes() == b"SENTINEL"


def test_the_same_file_under_different_declarations_is_a_different_job(tmp_path: Path) -> None:
    step = export_part(_demo("plate-edge-close"), tmp_path)
    raw = step.read_bytes()
    static = UsageContext(material_series="7xxx", loading=Loading.STATIC)
    assert job_key(raw, CYCLIC_7XXX) != job_key(raw, static)


def test_a_submitted_name_cannot_escape_the_delivery_folder(tmp_path: Path) -> None:
    step = export_part(_demo("plate-clean"), tmp_path)
    with pytest.raises(ValueError, match="plain name"):
        run_job(step, CYCLIC_7XXX, tmp_path / "out", part_name="../../etc/passwd")


def test_rebuild_that_measures_differently_is_caught() -> None:
    def measurement(value: float) -> Measurement:
        return Measurement(
            feature_id="hole-1",
            feature_type=FeatureType.HOLE,
            quantity="hole_diameter_mm",
            value=value,
            unit="mm",
            method="test",
        )

    assert _rebuild_disagreement([measurement(6.0)], [measurement(6.0)]) is None
    assert "not faithful" in (_rebuild_disagreement([measurement(6.0)], [measurement(6.1)]) or "")
    assert "not the submitted part" in (_rebuild_disagreement([measurement(6.0)], []) or "")


def test_result_file_is_the_whole_delivery_and_reads_back(tmp_path: Path) -> None:
    result, _ = _run(_demo("plate-tight-thin"), tmp_path)
    saved = (tmp_path / "out" / RESULT_FILENAME).read_text(encoding="utf-8")
    assert JobResult.model_validate_json(saved) == result
    for role, filename in json.loads(saved)["files"].items():
        assert (tmp_path / "out" / filename).exists(), role


def test_command_line_runs_a_part_and_reports_its_status(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    step = export_part(_demo("plate-clean"), tmp_path)
    exit_code = main(
        [
            str(step),
            str(tmp_path / "out"),
            "--material-series",
            "7xxx",
            "--loading",
            "cyclic",
        ]
    )
    assert exit_code == 0
    assert json.loads(capsys.readouterr().out)["status"] == "clean"
    assert (tmp_path / "out" / RESULT_FILENAME).exists()


def test_a_delivered_job_never_shows_the_test_fixture_rule(tmp_path: Path) -> None:
    # Audit 2026-09-02: R-0005 exists to exercise the NOTE path of the
    # skeleton; it is "never publishable" by its own anchor, yet it reached
    # every visitor's report and once thickened a delivered plate.
    result, _ = _run(_demo("plate-tight-thin"), tmp_path)
    assert result.status is JobStatus.CORRECTED, result.reason
    assert {v.rule_id for v in result.violations} == {"R-0003"}
    assert {c.rule_id for c in result.corrections} == {"R-0003"}
    assert all("TEST FIXTURE" not in (v.explanation or "") for v in result.violations)


def test_the_delivered_reports_are_pdfs_with_the_part_drawn_in_them(tmp_path: Path) -> None:
    """Owner's order, 2026-09-20: what a visitor downloads is a PDF, not a
    markdown file. A fabrication package is filed and printed, and the
    correction report carries the plate itself, with the hole the machine moved
    marked where it was.
    """
    spec = _demo("plate-edge-close")
    result, _ = _run(spec, tmp_path)
    for role in ("inspection_report", "correction_report"):
        name = result.files[role]
        assert name.endswith(".pdf"), f"{role} is {name}"
        body = (tmp_path / "out" / name).read_bytes()
        assert body.startswith(b"%PDF-"), f"{role} is not a PDF"
        assert b"%%EOF" in body[-2048:], f"{role} has no end-of-file marker"
        # Read back what the page actually says, not just that a file exists.
        from pypdf import PdfReader

        text = "\n".join(page.extract_text() for page in PdfReader(BytesIO(body)).pages)
        assert "SCHEINMAN" in text and spec.name in text
        assert result.job_key in text, "a filed report must name the job it belongs to"
        assert "PRIVATE" in text, "a page that leaves the site carries its own status"
    inspection = (tmp_path / "out" / result.files["inspection_report"]).read_bytes()
    from pypdf import PdfReader

    text = "\n".join(page.extract_text() for page in PdfReader(BytesIO(inspection)).pages)
    # The measured number, the limit it broke and the sentence the limit came
    # from are all on the page: the claim and its evidence travel together.
    assert "1.333" in text and "R-0001" in text
    assert "edge distance should not be less than 2 times the diameter" in text
