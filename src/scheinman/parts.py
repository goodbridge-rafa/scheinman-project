"""Parametric test parts with planted violations and a known answer key.

The generator knows exactly what it planted; the measurer must rediscover it
from the exported STEP file alone. That gap is what makes the end-to-end test
honest.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from build123d import Axis, Box, Cylinder, Part, Pos, export_step, fillet

from scheinman.schemas import Loading, UsageContext


@dataclass(frozen=True)
class Hole:
    x: float
    y: float
    diameter: float


@dataclass(frozen=True)
class PartSpec:
    """One test part: geometry parameters, declared context, and the answer key."""

    name: str
    length: float
    width: float
    thickness: float
    holes: tuple[Hole, ...]
    context: UsageContext
    corner_fillet_radius: float = 0.0
    # Answer key: (rule_id, feature_id) pairs the verdict MUST report, and nothing else.
    planted: frozenset[tuple[str, str]] = field(default_factory=frozenset)
    # Where the plate's minimum corner sits in the exported file. None keeps the
    # generator's historical frame (a box centred on the origin); a part read
    # back from a submitted file carries that file's own frame, so the rebuilt
    # and corrected part lands exactly where the submitted one was
    # (audit 2026-09-02).
    origin: tuple[float, float, float] | None = None

    @property
    def frame_origin(self) -> tuple[float, float, float]:
        """The minimum corner of the exported solid, in file coordinates."""
        if self.origin is not None:
            return self.origin
        return (-self.length / 2, -self.width / 2, -self.thickness / 2)


def build_part(spec: PartSpec) -> Part:
    solid = Box(spec.length, spec.width, spec.thickness)
    if spec.corner_fillet_radius > 0:
        solid = fillet(solid.edges().filter_by(Axis.Z), spec.corner_fillet_radius)
    for hole in spec.holes:
        # Box is centered at the origin; hole coordinates are given from the corner.
        cx = hole.x - spec.length / 2
        cy = hole.y - spec.width / 2
        solid -= Pos(cx, cy, 0) * Cylinder(hole.diameter / 2, spec.thickness * 2)
    if spec.origin is not None:
        # Move the centred solid so its minimum corner sits at the file's origin.
        ox, oy, oz = spec.origin
        solid = Pos(ox + spec.length / 2, oy + spec.width / 2, oz + spec.thickness / 2) * solid
    return solid


def export_part(spec: PartSpec, directory: Path) -> Path:
    path = directory / f"{spec.name}.step"
    export_step(build_part(spec), str(path))
    return path


def stage1_parts() -> tuple[PartSpec, ...]:
    """The three stage-1 parts. Feature ids follow the measurer's convention:
    holes sorted by (x, y) become hole-1..n; pairs become hole-i+hole-j."""
    clean = PartSpec(
        name="plate-clean",
        length=100,
        width=60,
        thickness=2,
        # d/t = 3.25: comfortably above rule R-0004's 3.0 floor. The old d=6
        # sat exactly ON the threshold, one rounding wobble from a false
        # positive (deep audit 2026-09-01).
        holes=(Hole(20, 20, 6.5), Hole(50, 20, 6.5), Hole(80, 20, 6.5)),
        context=UsageContext(material_series="7xxx", loading=Loading.CYCLIC),
        corner_fillet_radius=3,
        planted=frozenset(),
    )
    edge_close = PartSpec(
        name="plate-edge-close",
        length=100,
        width=60,
        thickness=2,
        holes=(Hole(10, 8, 6), Hole(60, 30, 6)),
        context=UsageContext(material_series="7xxx", loading=Loading.CYCLIC),
        planted=frozenset(
            {
                ("R-0001", "hole-1"),  # e/D 1.33 < 2.0, 7xxx + cyclic: BLOCK
                ("R-0002", "hole-1"),  # same measurement breaks the generic WARN too
            }
        ),
    )
    tight_thin = PartSpec(
        name="plate-tight-thin",
        length=90,
        width=50,
        thickness=0.8,
        holes=(Hole(40, 25, 4), Hole(49, 25, 4)),
        context=UsageContext(material_series="6xxx", loading=Loading.STATIC),
        planted=frozenset(
            {
                ("R-0003", "hole-1+hole-2"),  # pitch 9mm / d4 = 2.25 < 3.0: WARN
                ("R-0005", "part"),  # thickness 0.8 < 1.0 fixture floor: NOTE
            }
        ),
    )
    return (clean, edge_close, tight_thin)
