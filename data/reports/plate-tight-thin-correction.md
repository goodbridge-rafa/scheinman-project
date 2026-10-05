# Correction report: plate-tight-thin

Declared context: material series 6xxx, loading static.

## Violations found on the submitted part

- WARN R-0003 at hole-1+hole-2: measured 2.25 ratio, required minimum 3 ratio
  scope: AC 43.13-1B states the 3.0-diameter spacing for single-row riveted sheet joints. Applied here to every pair of round through-holes in any plate, on the same row or not. The ratio is the pitch over the average diameter of the two holes, a project convention: the source speaks of one rivet diameter. Not for lightening, drain or pin holes.

## Corrections applied (arithmetic on part parameters)

- rule R-0003 (hole_pitch_over_diameter): moved one hole of hole-1+hole-2 away from the other, raising the pitch from 9 mm to 12.24 mm (3.06 diameters: the minimum plus the project's 2% margin)

## Proof by re-measurement

The corrected file plate-tight-thin-corrected.step was re-exported, re-measured by the same measurer, and re-judged by the same rules (R-0001, R-0002, R-0003, R-0004) in 1 correction round(s): zero WARN or BLOCK violations remain.

- part: thickness_mm = 0.800 mm
- hole-1: hole_diameter_mm = 4.000 mm
- hole-1: hole_diameter_over_thickness = 5.000 ratio
- hole-1: edge_distance_over_diameter = 6.250 ratio
- hole-2: hole_diameter_mm = 4.000 mm
- hole-2: hole_diameter_over_thickness = 5.000 ratio
- hole-2: edge_distance_over_diameter = 6.250 ratio
- hole-1+hole-2: hole_pitch_over_diameter = 3.060 ratio
