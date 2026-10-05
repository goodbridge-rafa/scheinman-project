# Inspection report: plate-tight-thin

Declared context: material series 6xxx, loading static. A CAD file holds shape, never purpose; the context above was declared by the requester.

## Measurements

- part: thickness_mm = 0.800 mm (smallest bounding-box dimension of the imported solid (plate assumption))
- hole-1: hole_diameter_mm = 4.000 mm (twice the radius of the grouped full-turn cylindrical faces of the hole)
- hole-1: hole_diameter_over_thickness = 5.000 ratio (measured hole diameter divided by measured plate thickness)
- hole-1: edge_distance_over_diameter = 6.250 ratio (shortest distance from hole axis to the outer boundary of the top face, divided by the measured hole diameter)
- hole-2: hole_diameter_mm = 4.000 mm (twice the radius of the grouped full-turn cylindrical faces of the hole)
- hole-2: hole_diameter_over_thickness = 5.000 ratio (measured hole diameter divided by measured plate thickness)
- hole-2: edge_distance_over_diameter = 6.250 ratio (shortest distance from hole axis to the outer boundary of the top face, divided by the measured hole diameter)
- hole-1+hole-2: hole_pitch_over_diameter = 2.250 ratio (center-to-center distance of each hole pair divided by their average measured diameter)

## Findings

### WARN: rule R-0003 at hole-1+hole-2

hole-1+hole-2: measured hole_pitch_over_diameter is 2.250 ratio, below the required minimum of 3 ratio. Fastener spacing below the canonical single-row minimum concentrates load between adjacent holes.

Scope: AC 43.13-1B states the 3.0-diameter spacing for single-row riveted sheet joints. Applied here to every pair of round through-holes in any plate, on the same row or not. The ratio is the pitch over the average diameter of the two holes, a project convention: the source speaks of one rivet diameter. Not for lightening, drain or pin holes.

Sources:
- FAA AC 43.13-1B CHG 1 (2001-09-27), Acceptable Methods, Techniques, and Practices - Aircraft Inspection and Repair - Chapter 4 (metal structure repair, riveting), PDF page 159 of 646; original stored at data/raw/AC_43.13-1B_w-chg1.pdf (faa.gov): "For single row rivets, the edge distance should not be less than 2 times the diameter of the rivet and spacing should not be less than 3 times the diameter of the rivet."
- scheinman measurement engine - hole-1+hole-2/hole_pitch_over_diameter: "hole_pitch_over_diameter = 2.250 ratio via center-to-center distance of each hole pair divided by their average measured diameter"

Not applicable to the declared context: R-0001.
