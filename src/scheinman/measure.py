"""Deterministic measurement of plate features from a STEP file.

No AI here, on purpose: SCHEINMAN's verdicts are arithmetic over measurements,
and this module is where the numbers come from. Every measurement carries the
method that produced it, so the number is auditable.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from itertools import combinations
from pathlib import Path

from build123d import Face, GeomType, Shape, Vertex, import_step
from OCP.BRepAdaptor import BRepAdaptor_Surface
from OCP.BRepExtrema import BRepExtrema_DistShapeShape
from OCP.gp import gp_Pnt, gp_Vec
from OCP.TopAbs import TopAbs_Orientation

from scheinman.schemas import FeatureType, Measurement

_FULL_TURN = 2 * math.pi


class UnmeasurableGeometryError(ValueError):
    """Geometry the measurer cannot classify. Raised instead of staying silent:
    an unmeasured feature would otherwise pass the verdict as compliant (audit
    2026-08-30: an edge-breaking hole vanished and the worst possible edge
    violation reported no violations)."""


@dataclass(frozen=True)
class _Cyl:
    x: float
    y: float
    radius: float
    span: float  # summed angular span of the grouped faces, radians
    concave: bool | None  # True = hole-like wall, False = fillet-like, None = mixed
    extent: float  # largest axial (V) extent among the grouped faces, mm


def _face_is_concave(face: Face, surface: BRepAdaptor_Surface) -> bool:
    """True when the face's outward normal points toward the cylinder axis.

    A hole wall is concave (out of the material means into the bore, toward the
    axis); a corner fillet is convex. This is what stops a partial notch from
    masquerading as a fillet."""
    cylinder = surface.Cylinder()
    u = (surface.FirstUParameter() + surface.LastUParameter()) / 2
    v = (surface.FirstVParameter() + surface.LastVParameter()) / 2
    pnt = gp_Pnt()
    d1u = gp_Vec()
    d1v = gp_Vec()
    surface.D1(u, v, pnt, d1u, d1v)
    normal = d1u.Crossed(d1v)
    if face.wrapped.Orientation() == TopAbs_Orientation.TopAbs_REVERSED:
        normal.Reverse()
    axis_dir = gp_Vec(cylinder.Axis().Direction())
    rel = gp_Vec(cylinder.Axis().Location(), pnt)
    radial = rel.Added(axis_dir.Multiplied(-rel.Dot(axis_dir)))
    return bool(normal.Dot(radial) < 0)


def _vertical_cylinders(shape: Shape) -> list[_Cyl]:
    """Group cylindrical faces by (axis position, radius); sum spans, keep sense.

    A through-hole shows up as concave faces summing to a full turn; a corner
    fillet on a vertical edge shows up as a convex quarter turn.
    """
    spans: dict[tuple[float, float, float], float] = {}
    senses: dict[tuple[float, float, float], set[bool]] = {}
    extents: dict[tuple[float, float, float], float] = {}
    # The key rounds to a micrometre only to GROUP the faces of one cylinder;
    # the values reported are the kernel's exact numbers from the first face.
    # A 3/8 inch hole (r = 4.7625 mm) used to be measured as 4.762 or 4.763
    # (verifier 2026-09-02): half a micrometre on every diameter, and a bore
    # area off by more than the plate check tolerates.
    exact: dict[tuple[float, float, float], tuple[float, float, float]] = {}
    for face in shape.faces():
        # Only planes (plate faces) and cylinders (holes, fillets) are known
        # geometry. Anything else — cones, tori, splines — would be silently
        # unmeasured, so it is refused instead (deep audit 2026-09-01).
        if face.geom_type == GeomType.PLANE:
            continue
        if face.geom_type != GeomType.CYLINDER:
            raise UnmeasurableGeometryError(
                f"unsupported face type {face.geom_type.name} — this measurer knows "
                "flat plates with straight vertical holes and corner fillets only; "
                "an unmeasured face would pass the verdict as compliant, so the "
                "part is refused instead"
            )
        surface = BRepAdaptor_Surface(face.wrapped)
        cylinder = surface.Cylinder()
        direction = cylinder.Axis().Direction()
        if abs(direction.Z()) < 0.99:
            # Deep audit 2026-09-01: these used to be skipped in silence, so a
            # side-drilled hole vanished from the measurement entirely.
            raise UnmeasurableGeometryError(
                f"cylindrical face whose axis is not vertical (|Z| = "
                f"{abs(direction.Z()):.3f}) — a tilted or side-drilled feature "
                "cannot be measured faithfully by the plate measurer, so the part "
                "is refused instead of silently under-measured"
            )
        location = cylinder.Axis().Location()
        key = (round(location.X(), 3), round(location.Y(), 3), round(cylinder.Radius(), 3))
        exact.setdefault(key, (location.X(), location.Y(), cylinder.Radius()))
        span = abs(surface.LastUParameter() - surface.FirstUParameter())
        spans[key] = spans.get(key, 0.0) + span
        senses.setdefault(key, set()).add(_face_is_concave(face, surface))
        extent = abs(surface.LastVParameter() - surface.FirstVParameter())
        extents[key] = max(extents.get(key, 0.0), extent)
    return [
        _Cyl(
            x,
            y,
            r,
            span,
            concave=next(iter(senses[k])) if len(senses[k]) == 1 else None,
            extent=extents[k],
        )
        for k, span in spans.items()
        for (x, y, r) in [exact[k]]
    ]


def _wrong_solid_count(path: Path, found: int) -> str:
    """Say which of the two very different problems this is.

    Loop test 2026-09-01: a corrupt file reached the visitor as "found 0
    solids", which reads like an empty assembly. A file the kernel could not
    parse and a file holding three parts are different problems and deserve
    different sentences.
    """
    if found == 0:
        return (
            f"{path.name}: no 3D solid could be read from this file. Either it is not a "
            "STEP file the kernel can parse, or it carries only surfaces and curves "
            "instead of a solid body"
        )
    return (
        f"{path.name}: this file holds {found} separate parts. The measurer works on one "
        "part at a time, so send them one per file"
    )


@dataclass(frozen=True)
class PlateDescription:
    """The plate's parameters, read back from a file nobody described to us.

    Measuring answers "is this part compliant"; correcting needs the parameters
    themselves, because the corrector works by arithmetic on parameters and
    never edits STEP text. Read is not trust: whoever rebuilds a part from this
    must prove the rebuild re-measures identically before correcting it.
    """

    length: float
    width: float
    thickness: float
    corner_fillet_radius: float
    holes: tuple[tuple[float, float, float], ...]  # x, y from the corner, diameter
    # Where the plate's minimum corner sits in the file's own coordinates. Real
    # exports are seldom centred on the origin; the corrected part must be
    # rebuilt exactly where the submitted one was (audit 2026-09-02).
    origin: tuple[float, float, float] = (0.0, 0.0, 0.0)


def _top_face(shape: Shape) -> Face:
    planar_tops = [
        f
        for f in shape.faces()
        if f.geom_type == GeomType.PLANE and abs(f.normal_at(f.center()).Z) > 0.99
    ]
    return max(planar_tops, key=lambda f: (round(f.center().Z, 3), f.area))


def describe_plate(path: Path) -> PlateDescription:
    """Read a plate's parameters back from its STEP file.

    Refuses anything the parameters could not describe faithfully — a
    non-rectangular outline, unequal or partial corner fillets — because a
    wrong parameter would rebuild a different part while every downstream
    report kept claiming it was the submitted one.
    """
    compound = import_step(str(path))
    solids = compound.solids()
    if len(solids) != 1:
        raise UnmeasurableGeometryError(_wrong_solid_count(path, len(solids)))
    solid = solids[0]
    bbox = solid.bounding_box()
    length, width, thickness = bbox.size.X, bbox.size.Y, bbox.size.Z
    if abs(thickness - min(length, width, thickness)) > 1e-6:
        raise UnmeasurableGeometryError(
            f"{path.name}: plate assumption violated — the smallest dimension is not "
            "the Z extent, so this is not a flat plate lying in XY"
        )
    cylinders = _vertical_cylinders(solid)
    holes = sorted(
        (c for c in cylinders if c.concave is True and c.span > 0.9 * _FULL_TURN),
        key=lambda c: (round(c.x, 1), round(c.y, 1)),
    )
    fillets = [
        c
        for c in cylinders
        if c.concave is False and 0.15 * _FULL_TURN < c.span < 0.35 * _FULL_TURN
    ]
    radii = {round(f.radius, 3) for f in fillets}
    if fillets and (len(fillets) != 4 or len(radii) != 1):
        raise UnmeasurableGeometryError(
            f"{path.name}: {len(fillets)} rounded vertical corner(s) with radii "
            f"{sorted(radii)} — the plate description covers a rectangle with four "
            "equal corner fillets or none, so this outline is refused instead of "
            "rebuilt as something it is not"
        )
    radius = radii.pop() if radii else 0.0
    top = _top_face(solid)
    kinds = {e.geom_type for e in top.outer_wire().edges()}
    if not kinds <= {GeomType.LINE, GeomType.CIRCLE}:
        raise UnmeasurableGeometryError(
            f"{path.name}: the outline contains {sorted(k.name for k in kinds)} edges — "
            "only straight sides and circular corner arcs can be described as a plate"
        )
    # A rectangle minus four fillet corners has exactly this area. Any notch,
    # slot or trimmed side moves it, and no parameter set could describe it.
    expected = length * width - (4 - math.pi) * radius**2
    bores = sum(math.pi * h.radius**2 for h in holes)
    # One part in a million of the area (0.024 mm2 on 400 x 300), not one in ten
    # thousand: a 1 mm keying notch on a big plate used to fit inside the old
    # tolerance and be dropped from the rebuild (audit 2026-09-02).
    if abs(top.area + bores - expected) > max(1e-3, 1e-6 * expected):
        raise UnmeasurableGeometryError(
            f"{path.name}: the top face area ({top.area + bores:.3f} mm2 with the bores "
            f"filled) does not match the {length:g} x {width:g} mm rectangle it would "
            f"have to be ({expected:.3f} mm2), so the outline is not a plain plate"
        )
    # Hole centres are absolute in the file; the plate's parameters are taken
    # from its minimum corner. Adding half the SIZE (the old code) assumed a
    # solid centred on the origin and mirrored every hole of a corner-origin
    # export while every distance still agreed (audit 2026-09-02).
    origin = (bbox.min.X, bbox.min.Y, bbox.min.Z)
    return PlateDescription(
        length=length,
        width=width,
        thickness=thickness,
        corner_fillet_radius=radius,
        holes=tuple((h.x - origin[0], h.y - origin[1], 2 * h.radius) for h in holes),
        origin=origin,
    )


def _outer_wire(shape: Shape) -> Shape:
    """Outer boundary of the top face: the plate edge the fastener rules measure to."""
    return _top_face(shape).outer_wire()


def _distance(a: Shape, b: Shape) -> float:
    calc = BRepExtrema_DistShapeShape(a.wrapped, b.wrapped)
    if not calc.IsDone():  # pragma: no cover - kernel failure would be a real bug
        raise RuntimeError("distance computation failed")
    return float(calc.Value())


def measure_step_file(path: Path) -> list[Measurement]:
    compound = import_step(str(path))
    solids = compound.solids()
    if len(solids) != 1:
        raise UnmeasurableGeometryError(_wrong_solid_count(path, len(solids)))
    solid = solids[0]

    measurements: list[Measurement] = []
    bbox = solid.bounding_box()
    sizes = sorted((bbox.size.X, bbox.size.Y, bbox.size.Z))
    if abs(bbox.size.Z - sizes[0]) > 1e-6:
        raise UnmeasurableGeometryError(
            f"{path.name}: plate assumption violated — the smallest dimension "
            f"({sizes[0]:g} mm) is not the Z extent ({bbox.size.Z:g} mm), so this is "
            "not a flat plate lying in XY and every derived quantity would be wrong"
        )
    measurements.append(
        Measurement(
            feature_id="part",
            feature_type=FeatureType.THICKNESS,
            quantity="thickness_mm",
            value=sizes[0],
            unit="mm",
            method="smallest bounding-box dimension of the imported solid (plate assumption)",
        )
    )

    cylinders = _vertical_cylinders(solid)
    holes = sorted(
        (c for c in cylinders if c.concave is True and c.span > 0.9 * _FULL_TURN),
        key=lambda c: (round(c.x, 1), round(c.y, 1)),
    )
    shallow = [h for h in holes if h.extent < sizes[0] - 1e-3]
    if shallow:
        detail = "; ".join(
            f"({h.x:g}, {h.y:g}) r={h.radius:g} depth {h.extent:g} of {sizes[0]:g} mm"
            for h in shallow
        )
        raise UnmeasurableGeometryError(
            f"{path.name}: hole depth short of the plate thickness — {detail}. A blind "
            "hole is not the through-hole the fastener rules reason about, so the part "
            "is refused instead of measured as if it were"
        )
    centers: dict[tuple[float, float], int] = {}
    for h in holes:
        centers[(round(h.x, 1), round(h.y, 1))] = centers.get((round(h.x, 1), round(h.y, 1)), 0) + 1
    stacked = [c for c, n in centers.items() if n > 1]
    if stacked:
        raise UnmeasurableGeometryError(
            f"{path.name}: coaxial cylindrical walls at {stacked} — a counterbored or "
            "stepped hole is not one measurable through-hole, so the part is refused "
            "instead of counted twice"
        )
    fillets = [
        c
        for c in cylinders
        if c.concave is False and 0.15 * _FULL_TURN < c.span < 0.35 * _FULL_TURN
    ]
    unclassified = [c for c in cylinders if c not in holes and c not in fillets]
    if unclassified:
        detail = "; ".join(
            f"cylindrical cut at ({c.x:g}, {c.y:g}) r={c.radius:g} spanning "
            f"{math.degrees(c.span):.0f} degrees "
            f"({'concave' if c.concave else 'convex' if c.concave is False else 'mixed'})"
            for c in unclassified
        )
        raise UnmeasurableGeometryError(
            f"{path.name}: geometry this measurer cannot classify — {detail}. "
            "A hole that breaks the plate boundary or overlaps another cannot be "
            "measured faithfully, so the part is refused instead of passed."
        )
    top = _top_face(solid)
    # Every through-hole is exactly one inner wire of the top face. Any other
    # inner wire is a window, slot or pocket the plate measurer does not see
    # (planar walls are skipped on purpose), and a hole beside it would be
    # judged against the wrong edge (audit 2026-09-02).
    inner = top.inner_wires()
    if len(inner) != len(holes):
        raise UnmeasurableGeometryError(
            f"{path.name}: the top face has {len(inner) - len(holes)} cut-out(s) that "
            "are not round through-holes (a window, slot or pocket); this measurer "
            "measures distances to the outer edge and to round holes only, so a hole "
            "beside such a cut-out would be judged against the wrong edge and the "
            "part is refused instead"
        )
    outer = top.outer_wire()
    top_z = bbox.max.Z

    named = [(f"hole-{i + 1}", hole) for i, hole in enumerate(holes)]
    for feature_id, hole in named:
        diameter = 2 * hole.radius
        measurements.append(
            Measurement(
                feature_id=feature_id,
                feature_type=FeatureType.HOLE,
                quantity="hole_diameter_mm",
                value=diameter,
                unit="mm",
                method="twice the radius of the grouped full-turn cylindrical faces of the hole",
            )
        )
        measurements.append(
            Measurement(
                feature_id=feature_id,
                feature_type=FeatureType.HOLE,
                quantity="hole_diameter_over_thickness",
                value=diameter / sizes[0],
                unit="ratio",
                method="measured hole diameter divided by measured plate thickness",
            )
        )
        edge = _distance(Vertex(hole.x, hole.y, top_z), outer)
        measurements.append(
            Measurement(
                feature_id=feature_id,
                feature_type=FeatureType.EDGE_DISTANCE,
                quantity="edge_distance_over_diameter",
                value=edge / diameter,
                unit="ratio",
                method="shortest distance from hole axis to the outer boundary of the top face, "
                "divided by the measured hole diameter",
            )
        )
    # Every pair, not only sort-adjacent ones: audit 2026-08-30 showed the
    # closest pair of three off-row holes escaping measurement entirely.
    for (id_a, a), (id_b, b) in combinations(named, 2):
        pitch = math.dist((a.x, a.y), (b.x, b.y))
        diameter = a.radius + b.radius  # average diameter of the pair
        measurements.append(
            Measurement(
                feature_id=f"{id_a}+{id_b}",
                feature_type=FeatureType.HOLE,
                quantity="hole_pitch_over_diameter",
                value=pitch / diameter,
                unit="ratio",
                method="center-to-center distance of each hole pair divided by their "
                "average measured diameter",
            )
        )
    for i, fil in enumerate(sorted(fillets, key=lambda c: (round(c.x, 1), round(c.y, 1)))):
        measurements.append(
            Measurement(
                feature_id=f"corner-fillet-{i + 1}",
                feature_type=FeatureType.CORNER_FILLET,
                quantity="corner_fillet_radius_mm",
                value=fil.radius,
                unit="mm",
                method="radius of the quarter-turn cylindrical face on a vertical corner edge",
            )
        )
    return measurements
