# Correction report: plate-edge-close

Declared context: material series 7xxx, loading cyclic.

## Violations found on the submitted part

- BLOCK R-0001 at hole-1: measured 1.333 ratio, required minimum 2 ratio
  scope: AC 43.13-1B states the 2.0-diameter edge distance for single-row riveted sheet joints. This project applies it to every round through-hole in a 7xxx plate declared under cyclic loading, as if each hole were a fastener hole. The cited ADs document fatigue cracking at fastener holes in 7xxx floor beams (7050-T7451 in E7-9396, 7075 in 00-4568); they do not state the edge distance of the cracked holes, and the repair in AD E7-9396 accepts an oversized fastener with a minimum edge margin of 1.7 D. Not for lightening, drain or pin holes.
- WARN R-0002 at hole-1: measured 1.333 ratio, required minimum 2 ratio
  scope: AC 43.13-1B states the 2.0-diameter edge distance for single-row riveted sheet joints. Applied here to every round through-hole in any plate, whatever the loading, as a fastener hole. Not for lightening, drain or pin holes.

## Corrections applied (arithmetic on part parameters)

- rule R-0001 (edge_distance_over_diameter): moved hole-1 center from (10, 8) to (12.24, 12.24) mm so its edge distance reaches 12.24 mm (2.04 diameters: the minimum plus the project's 2% margin)
- rule R-0002 (edge_distance_over_diameter): hole-1 already repositioned by an earlier correction in this pass; no additional change

## Proof by re-measurement

The corrected file plate-edge-close-corrected.step was re-exported, re-measured by the same measurer, and re-judged by the same rules (R-0001, R-0002, R-0003, R-0004) in 1 correction round(s): zero WARN or BLOCK violations remain.

- part: thickness_mm = 2.000 mm
- hole-1: hole_diameter_mm = 6.000 mm
- hole-1: hole_diameter_over_thickness = 3.000 ratio
- hole-1: edge_distance_over_diameter = 2.040 ratio
- hole-2: hole_diameter_mm = 6.000 mm
- hole-2: hole_diameter_over_thickness = 3.000 ratio
- hole-2: edge_distance_over_diameter = 5.000 ratio
- hole-1+hole-2: hole_pitch_over_diameter = 8.493 ratio
