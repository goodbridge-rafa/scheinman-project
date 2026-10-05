"""The measurer must refuse geometry it cannot measure faithfully.

Audit 2026-08-30 found the worst possible violations passing silently: a hole
breaking the plate edge vanished from measurement, an ~83-degree notch could
masquerade as a corner fillet, and pitch was only measured between
sort-adjacent holes. These tests pin the honest behavior.
"""

from pathlib import Path
from typing import Any

import pytest

from scheinman.measure import UnmeasurableGeometryError, measure_step_file
from scheinman.parts import Hole, PartSpec, export_part
from scheinman.schemas import Loading, UsageContext

CTX = UsageContext(material_series="7xxx", loading=Loading.CYCLIC)


def _measure(spec: PartSpec, tmp_path: Path):  # type: ignore[no-untyped-def]
    return measure_step_file(export_part(spec, tmp_path))


def test_edge_breaking_hole_is_refused_not_silenced(tmp_path: Path) -> None:
    spec = PartSpec(
        name="edge-breaker",
        length=100,
        width=60,
        thickness=2,
        holes=(Hole(2, 30, 6),),
        context=CTX,
    )
    with pytest.raises(UnmeasurableGeometryError):
        _measure(spec, tmp_path)


def test_overlapping_holes_are_refused_not_silenced(tmp_path: Path) -> None:
    spec = PartSpec(
        name="overlappers",
        length=100,
        width=60,
        thickness=2,
        holes=(Hole(40, 30, 6), Hole(44, 30, 6)),
        context=CTX,
    )
    with pytest.raises(UnmeasurableGeometryError):
        _measure(spec, tmp_path)


def test_pitch_is_measured_between_every_pair(tmp_path: Path) -> None:
    # The truly close pair (10,10)-(12,11) is not sort-adjacent; before the fix
    # its 1.12 ratio was never measured and rule R-0003 stayed green.
    spec = PartSpec(
        name="pitch-blind",
        length=100,
        width=60,
        thickness=2,
        holes=(Hole(10, 10, 2), Hole(11, 50, 2), Hole(12, 11, 2)),
        context=CTX,
    )
    pitches = {
        m.feature_id: m.value
        for m in _measure(spec, tmp_path)
        if m.quantity == "hole_pitch_over_diameter"
    }
    assert len(pitches) == 3
    assert min(pitches.values()) == pytest.approx(1.118, abs=0.01)


def test_clean_stage1_part_still_measures(tmp_path: Path) -> None:
    from scheinman.parts import stage1_parts

    clean = stage1_parts()[0]
    ms = _measure(clean, tmp_path)
    assert sum(1 for m in ms if m.quantity == "hole_diameter_mm") == 3
    assert sum(1 for m in ms if m.quantity == "corner_fillet_radius_mm") == 4


def _base_plate() -> Any:
    from build123d import Box

    return Box(100, 60, 2)


def test_sideways_hole_is_refused_not_ignored(tmp_path: Path) -> None:
    # Deep audit 2026-09-01: non-vertical cylinder axes were silently skipped,
    # so a side-drilled hole simply vanished from the measurement.
    from build123d import Cylinder, Pos, Rot, export_step

    solid = _base_plate() - Pos(0, 0, 0) * Rot(90, 0, 0) * Cylinder(0.5, 200)
    path = tmp_path / "sideways.step"
    export_step(solid, str(path))
    with pytest.raises(UnmeasurableGeometryError, match="not vertical"):
        measure_step_file(path)


def test_conical_countersink_is_refused_not_ignored(tmp_path: Path) -> None:
    from build123d import Cone, Cylinder, Pos, export_step

    solid = _base_plate() - Cylinder(3, 10) - Pos(0, 0, 0.5) * Cone(6, 3, 1)
    path = tmp_path / "countersink.step"
    export_step(solid, str(path))
    with pytest.raises(UnmeasurableGeometryError, match="face type"):
        measure_step_file(path)


def test_blind_hole_is_refused_not_measured_as_through(tmp_path: Path) -> None:
    from build123d import Cylinder, Pos, export_step

    solid = _base_plate() - Pos(0, 0, 0.5) * Cylinder(3, 2)  # stops 0.5 mm short
    path = tmp_path / "blind.step"
    export_step(solid, str(path))
    with pytest.raises(UnmeasurableGeometryError, match="depth"):
        measure_step_file(path)


def test_coaxial_counterbore_is_refused_not_counted_twice(tmp_path: Path) -> None:
    from build123d import Cylinder, Pos, export_step

    solid = _base_plate() - Cylinder(3, 10) - Pos(0, 0, 0.75) * Cylinder(5, 0.5)
    path = tmp_path / "counterbore.step"
    export_step(solid, str(path))
    with pytest.raises(UnmeasurableGeometryError, match="coaxial|depth"):
        measure_step_file(path)


def test_tall_part_violates_the_plate_assumption_loudly(tmp_path: Path) -> None:
    from build123d import Box, export_step

    solid = Box(10, 8, 50)  # thickness axis is not Z
    path = tmp_path / "tall.step"
    export_step(solid, str(path))
    with pytest.raises(UnmeasurableGeometryError, match="plate assumption"):
        measure_step_file(path)


# --- Audit 2026-09-02: the file's own frame, not the origin -------------
#
# Real CAD exports rarely sit centred on the origin; a corner at the origin is
# the common case. The measurer's quantities are frame-free (distances, ratios),
# but describe_plate used to convert hole centres by adding half the plate SIZE,
# which silently mirrored every hole of a corner-origin export. Probe on
# 2026-09-02: a hole at (25, 15) of a 100 x 60 plate was described at (75, 45),
# every measurement agreed, and the rebuild would have shipped a different part.


def _corner_origin_export(spec: PartSpec, tmp_path: Path) -> Path:
    from build123d import Pos, export_step

    from scheinman.parts import build_part

    solid = Pos(spec.length / 2, spec.width / 2, spec.thickness / 2) * build_part(spec)
    path = tmp_path / f"{spec.name}-corner.step"
    export_step(solid, str(path))
    return path


def test_corner_origin_export_is_described_in_its_own_frame(tmp_path: Path) -> None:
    from scheinman.measure import describe_plate
    from scheinman.parts import stage1_parts

    spec = next(s for s in stage1_parts() if s.name == "plate-edge-close")
    plate = describe_plate(_corner_origin_export(spec, tmp_path))
    assert plate.holes == ((10.0, 8.0, 6.0), (60.0, 30.0, 6.0))
    assert plate.origin == (0.0, 0.0, 0.0)
    centred = describe_plate(export_part(spec, tmp_path))
    assert centred.holes == plate.holes
    assert centred.origin == (-50.0, -30.0, -1.0)


def test_corner_origin_export_is_corrected_in_place_not_mirrored(tmp_path: Path) -> None:
    from build123d import import_step

    from scheinman.job import JobStatus, run_job
    from scheinman.parts import stage1_parts

    spec = next(s for s in stage1_parts() if s.name == "plate-edge-close")
    path = _corner_origin_export(spec, tmp_path)
    result = run_job(path, spec.context, tmp_path / "out", part_name="corner")
    assert result.status is JobStatus.CORRECTED, result.reason
    delivered = tmp_path / "out" / result.files["corrected_step"]
    box = import_step(str(delivered)).solids()[0].bounding_box()
    # The corrected part lives where the submitted part lived: same frame.
    assert (round(box.min.X, 6), round(box.min.Y, 6), round(box.min.Z, 6)) == (0.0, 0.0, 0.0)


# --- Audit 2026-09-02: what the measurer cannot see, it must refuse ----
#
# Planar faces are skipped on purpose (they are the plate), so a window or a
# pocket cut through the plate left no trace in the measurement: a hole 4 mm
# from a window edge was judged against the outer edge only and passed clean.


def test_plate_with_a_window_is_refused_not_passed_clean(tmp_path: Path) -> None:
    from build123d import Box, Cylinder, Pos, export_step

    from scheinman.job import JobStatus, run_job

    plate = Box(100, 60, 2)
    plate -= Pos(-20, 0, 0) * Cylinder(3, 10)  # a proper through-hole
    plate -= Pos(10, 0, 0) * Box(30, 20, 10)  # a rectangular window beside it
    path = tmp_path / "windowed.step"
    export_step(plate, str(path))
    with pytest.raises(UnmeasurableGeometryError, match="cut-out"):
        measure_step_file(path)
    result = run_job(path, CTX, tmp_path / "out", part_name="windowed")
    assert result.status is JobStatus.REFUSED
    assert "cut-out" in (result.reason or "")


# --- Audit 2026-09-02: a notch must not hide inside a big plate --------


def test_keying_notch_on_a_big_plate_is_refused_not_dropped(tmp_path: Path) -> None:
    from build123d import Box, Cylinder, Pos, export_step

    from scheinman.measure import describe_plate

    plate = Box(400, 300, 3)
    plate -= Pos(-150, -100, 0) * Cylinder(4, 10)
    plate -= Pos(200, 0, 0) * Box(4, 2, 10)  # a 2 x 2 mm keying notch on the long edge
    path = tmp_path / "notched.step"
    export_step(plate, str(path))
    with pytest.raises(UnmeasurableGeometryError, match="not a plain plate"):
        describe_plate(path)


# --- Verifier 2026-09-02: exact numbers, a rounded key only for grouping ------


def test_an_inch_sized_hole_is_measured_exactly_not_to_the_nearest_micrometre(
    tmp_path: Path,
) -> None:
    from scheinman.measure import describe_plate

    spec = PartSpec(
        name="inch-holes",
        length=100,
        width=60,
        thickness=2,
        holes=(Hole(30, 30, 2 * 4.7625), Hole(70, 30, 2 * 3.96875)),  # 3/8 in and 5/16 in
        context=CTX,
    )
    diameters = {
        m.feature_id: m.value for m in _measure(spec, tmp_path) if m.quantity == "hole_diameter_mm"
    }
    assert diameters["hole-1"] == pytest.approx(9.525, abs=1e-9)
    assert diameters["hole-2"] == pytest.approx(7.9375, abs=1e-9)
    plate = describe_plate(export_part(spec, tmp_path))  # a plain plate stays a plain plate
    assert [round(d, 6) for _, _, d in plate.holes] == [9.525, 7.9375]
