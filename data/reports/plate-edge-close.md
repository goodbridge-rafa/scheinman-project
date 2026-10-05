# Inspection report: plate-edge-close

Declared context: material series 7xxx, loading cyclic. A CAD file holds shape, never purpose; the context above was declared by the requester.

## Measurements

- part: thickness_mm = 2.000 mm (smallest bounding-box dimension of the imported solid (plate assumption))
- hole-1: hole_diameter_mm = 6.000 mm (twice the radius of the grouped full-turn cylindrical faces of the hole)
- hole-1: hole_diameter_over_thickness = 3.000 ratio (measured hole diameter divided by measured plate thickness)
- hole-1: edge_distance_over_diameter = 1.333 ratio (shortest distance from hole axis to the outer boundary of the top face, divided by the measured hole diameter)
- hole-2: hole_diameter_mm = 6.000 mm (twice the radius of the grouped full-turn cylindrical faces of the hole)
- hole-2: hole_diameter_over_thickness = 3.000 ratio (measured hole diameter divided by measured plate thickness)
- hole-2: edge_distance_over_diameter = 5.000 ratio (shortest distance from hole axis to the outer boundary of the top face, divided by the measured hole diameter)
- hole-1+hole-2: hole_pitch_over_diameter = 9.104 ratio (center-to-center distance of each hole pair divided by their average measured diameter)

## Findings

### BLOCK: rule R-0001 at hole-1

hole-1: measured edge_distance_over_diameter is 1.333 ratio, below the required minimum of 2 ratio. Fatigue cracking originating at fastener holes in 7xxx-series primary structure under cyclic loading is documented in service (ADs E7-9396 and 00-4568). The 2.0-diameter edge-distance minimum is the AC 43.13-1B repair practice for that feature; the record documents the location and the mechanism, not a measured edge distance of the cracked holes.

Scope: AC 43.13-1B states the 2.0-diameter edge distance for single-row riveted sheet joints. This project applies it to every round through-hole in a 7xxx plate declared under cyclic loading, as if each hole were a fastener hole. The cited ADs document fatigue cracking at fastener holes in 7xxx floor beams (7050-T7451 in E7-9396, 7075 in 00-4568); they do not state the edge distance of the cracked holes, and the repair in AD E7-9396 accepts an oversized fastener with a minimum edge margin of 1.7 D. Not for lightening, drain or pin holes.

Sources:
- FAA AC 43.13-1B CHG 1 (2001-09-27), Acceptable Methods, Techniques, and Practices - Aircraft Inspection and Repair - Chapter 4 (metal structure repair, riveting), PDF page 159 of 646; original stored at data/raw/AC_43.13-1B_w-chg1.pdf (faa.gov): "For single row rivets, the edge distance should not be less than 2 times the diameter of the rivet and spacing should not be less than 3 times the diameter of the rivet."
- FAA Airworthiness Directive, Federal Register document E7-9396 (2007-05-17), Boeing Model 747-400 - data/raw/ads/E7-9396.txt (fetched from federalregister.gov full-text endpoint; hash-identical pilot copy also at data/raw/AD-E7-9396.txt); summary and Boeing clarification passages: "This AD results from several reports indicating that fatigue cracking was found in upper deck floor beams made from 7000 series aluminum alloy. [...] cracking was found on airplanes with 7075-T6 upper deck floor beams, which prompted issuance of other related rulemaking [...] which include inspecting the floor beam web and chords, certain fastener holes at the intersection of the floor beam and frame"
- FAA Airworthiness Directive, Federal Register document 00-4568 (2000-02-29), Boeing Model 747-100, -200, and -300 Series Airplanes - data/raw/ads/00-4568.txt (fetched from federalregister.gov full-text endpoint); double-agreed facts in data/facts/lot4-ads/merged.json: "The report also indicates that the floor beams at BS 340 and 360 are made from 7075 aluminum, a material which is more susceptible to fatigue cracking than 2024 aluminum. [...] this AD is being issued to prevent failure of the upper deck floor beams at BS 340, 360, and 380 due to fatigue cracking that originates from the upper chord fastener holes of those floor beams"
- scheinman measurement engine - hole-1/edge_distance_over_diameter: "edge_distance_over_diameter = 1.333 ratio via shortest distance from hole axis to the outer boundary of the top face, divided by the measured hole diameter"

### WARN: rule R-0002 at hole-1

hole-1: measured edge_distance_over_diameter is 1.333 ratio, below the required minimum of 2 ratio. Edge distance below the canonical single-row minimum weakens the joint regardless of loading. Fatigue events at fastener holes support the mechanism (the fusion record counts them), but a rule that claims any material and any loading is an unbounded claim no finite set of events can cover, so by policy (scheinman.fusion) it stays WARN and never blocks.

Scope: AC 43.13-1B states the 2.0-diameter edge distance for single-row riveted sheet joints. Applied here to every round through-hole in any plate, whatever the loading, as a fastener hole. Not for lightening, drain or pin holes.

Sources:
- FAA AC 43.13-1B CHG 1 (2001-09-27), Acceptable Methods, Techniques, and Practices - Aircraft Inspection and Repair - Chapter 4 (metal structure repair, riveting), PDF page 159 of 646; original stored at data/raw/AC_43.13-1B_w-chg1.pdf (faa.gov): "For single row rivets, the edge distance should not be less than 2 times the diameter of the rivet and spacing should not be less than 3 times the diameter of the rivet."
- scheinman measurement engine - hole-1/edge_distance_over_diameter: "edge_distance_over_diameter = 1.333 ratio via shortest distance from hole axis to the outer boundary of the top face, divided by the measured hole diameter"

