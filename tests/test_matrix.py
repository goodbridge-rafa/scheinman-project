"""The loop test: many shapes of part, one after another, through the whole engine.

Unit tests prove each guard alone. This proves the product: whatever a stranger
uploads, the job ends in a status the counter can draw, with a reason a person
can read, and never in a crash. Every case here was run for real on 2026-09-01
before being written down.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest
from build123d import Axis, Box, Cone, Cylinder, Pos, Rot, export_step, fillet

from scheinman.job import JobStatus, run_job
from scheinman.measure import measure_step_file
from scheinman.parts import export_part, stage1_parts
from scheinman.rules import publishable_rules
from scheinman.schemas import Loading, Severity, UsageContext
from scheinman.verdict import evaluate

CYCLIC_7XXX = UsageContext(material_series="7xxx", loading=Loading.CYCLIC)


def _step(solid: object, name: str, directory: Path) -> Path:
    path = directory / f"{name}.step"
    export_step(solid, str(path))
    return path


def _shapes(directory: Path) -> list[tuple[str, Path, JobStatus, str]]:
    """name, file, the ending it must reach, and a phrase the reason must carry."""
    plate = Box(100, 60, 2)
    grid = Box(400, 300, 4)
    for i in range(24):
        grid -= Pos(-160 + (i % 8) * 45, -100 + (i // 8) * 90, 0) * Cylinder(6, 20)
    corrupt = directory / "corrupt.step"
    corrupt.write_bytes(b"ISO-10303-21;\nHEADER;\nnot a real body\nEND-ISO-10303-21;\n")
    return [
        (
            "notched",
            _step(
                plate - Pos(50, 30, 0) * Box(20, 20, 10) - Pos(-40, -22, 0) * Cylinder(3, 10),
                "notched",
                directory,
            ),
            JobStatus.UNCORRECTED,
            "not a plain plate",
        ),
        (
            "sideways",
            _step(plate - Rot(90, 0, 0) * Cylinder(0.5, 200), "sideways", directory),
            JobStatus.REFUSED,
            "not vertical",
        ),
        (
            "countersink",
            _step(
                plate - Cylinder(3, 10) - Pos(0, 0, 0.5) * Cone(6, 3, 1), "countersink", directory
            ),
            JobStatus.REFUSED,
            "face type",
        ),
        (
            "blind",
            _step(plate - Pos(0, 0, 0.5) * Cylinder(3, 2), "blind", directory),
            JobStatus.REFUSED,
            "depth",
        ),
        ("tall", _step(Box(10, 8, 50), "tall", directory), JobStatus.REFUSED, "plate assumption"),
        (
            "assembly",
            _step(Box(30, 20, 2) + Pos(60, 0, 0) * Box(30, 20, 2), "assembly", directory),
            JobStatus.REFUSED,
            "separate parts",
        ),
        ("corrupt", corrupt, JobStatus.REFUSED, "no 3D solid could be read"),
        (
            "big-filleted",
            _step(
                fillet(
                    (
                        Box(300, 200, 6)
                        - Pos(-100, -60, 0) * Cylinder(6, 20)
                        - Pos(100, 60, 0) * Cylinder(6, 20)
                    )
                    .edges()
                    .filter_by(Axis.Z),
                    8,
                ),
                "big-filleted",
                directory,
            ),
            JobStatus.CORRECTED,
            "",
        ),
        ("grid-24-holes", _step(grid, "grid-24-holes", directory), JobStatus.CLEAN, ""),
    ]


def test_every_shape_ends_in_a_status_the_counter_can_draw() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        work = Path(tmp)
        for spec in stage1_parts():
            expected = JobStatus.CLEAN if spec.name == "plate-clean" else JobStatus.CORRECTED
            result = run_job(
                export_part(spec, work), spec.context, work / spec.name, part_name=spec.name
            )
            assert result.status is expected, f"{spec.name}: {result.status} {result.reason}"

        for name, path, expected, phrase in _shapes(work):
            result = run_job(path, CYCLIC_7XXX, work / f"out-{name}", part_name=name)
            assert result.status is expected, f"{name}: got {result.status.value} ({result.reason})"
            if phrase:
                assert phrase in (result.reason or ""), f"{name}: reason was {result.reason!r}"
            # Whatever the ending, the visitor is never handed a bare failure.
            if result.status is not JobStatus.CLEAN:
                assert result.reason or result.violations, f"{name} ended silent"
            if result.status is JobStatus.CORRECTED:
                # The status is not the proof; the shipped file is. Re-measure
                # it independently and re-judge it (audit 2026-09-02).
                shipped = work / f"out-{name}" / result.files["corrected_step"]
                remaining = evaluate(CYCLIC_7XXX, measure_step_file(shipped), publishable_rules())
                assert [v for v in remaining if v.severity is not Severity.NOTE] == [], name
                assert set(result.files) >= {
                    "submitted_step",
                    "inspection_report",
                    "corrected_step",
                }


def test_a_refusal_never_leaves_half_a_delivery_behind() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        work = Path(tmp)
        path = _step(Box(100, 60, 2) - Rot(90, 0, 0) * Cylinder(0.5, 200), "sideways", work)
        out = work / "delivery"
        result = run_job(path, CYCLIC_7XXX, out, part_name="sideways")
        assert result.status is JobStatus.REFUSED
        # The part the visitor sent is kept; nothing else is invented.
        assert set(result.files) == {"submitted_step"}
        assert sorted(p.name for p in out.iterdir()) == ["result.json", "sideways.step"]


@pytest.mark.parametrize("loading", [Loading.CYCLIC, Loading.STATIC])
def test_the_same_part_under_each_declared_loading_is_a_different_job(loading: Loading) -> None:
    with tempfile.TemporaryDirectory() as tmp:
        work = Path(tmp)
        spec = next(s for s in stage1_parts() if s.name == "plate-edge-close")
        context = UsageContext(material_series="7xxx", loading=loading)
        result = run_job(export_part(spec, work), context, work / loading.value, part_name="p")
        # Cyclic arms the strict fatigue rule; static does not. Both are honest
        # answers about the same geometry, which is the whole point of asking.
        severities = {v.severity.value for v in result.violations}
        assert ("BLOCK" in severities) is (loading is Loading.CYCLIC)
