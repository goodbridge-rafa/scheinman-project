"""The words both versions of the site say, with one owner.

Two skins serve the same product (owner's decision, 2026-09-10). Everything
about how a page looks belongs to that page; everything a page *says* about a
verdict, a refusal or a delivery belongs here, because the same sentence said
two slightly different ways on two pages is the same product telling two
stories. The vocabularies themselves are not defined here: the alloy series come
from `scheinman.schemas` and the job statuses from `scheinman.job`, the owners
registered in `ecosystem/CONTRACTS.md`. This module only adds the human words
for values those modules already close.

`scheinman.webbuild` injects `as_js()` into every page that needs it, so the
sentences reach a browser without either template holding a copy.
"""

from __future__ import annotations

import json

from scheinman.job import JobStatus
from scheinman.schemas import MATERIAL_SERIES

# What the visitor is choosing between. The keys are the closed vocabulary; the
# examples are the alloys an engineer recognises, so nobody has to know that the
# first digit of 7075-T6 is what the counter is asking for.
SERIES_EXAMPLES: dict[str, str] = {
    "1xxx": "pure aluminum (1100, 1050)",
    "2xxx": "copper alloys (2024, 2014, 2124)",
    "3xxx": "manganese alloys (3003, 3004)",
    "4xxx": "silicon alloys (4032, 4043)",
    "5xxx": "magnesium alloys (5052, 5083)",
    "6xxx": "magnesium-silicon alloys (6061, 6082)",
    "7xxx": "zinc alloys (7075, 7050, 7150)",
    "8xxx": "other alloys, incl. lithium (8090)",
}

# The order the counter offers them in: the series the engine has a fatigue rule
# for comes first, then the rest of the structural families, then the fringe.
SERIES_ORDER: tuple[str, ...] = ("7xxx", "2xxx", "6xxx", "5xxx", "3xxx", "1xxx", "4xxx", "8xxx")

DEFAULT_SERIES = "7xxx"

LOADINGS: tuple[tuple[str, str, str], ...] = (
    ("cyclic", "Cyclic", "vibrates or repeats"),
    ("static", "Static", "holds still"),
)

# What the measurer can produce, in the words a reader uses. The keys are the
# closed vocabulary (`schemas.KNOWN_QUANTITIES`, its owner); a test binds the two,
# so a quantity added there without a word here fails the build rather than
# reaching a page as a field name.
QUANTITY_WORDS: dict[str, str] = {
    "thickness_mm": "sheet thickness",
    "hole_diameter_mm": "hole diameter",
    "hole_diameter_over_thickness": "hole diameter over thickness",
    "edge_distance_over_diameter": "edge distance over hole diameter",
    "hole_pitch_over_diameter": "hole spacing over hole diameter",
    "corner_fillet_radius_mm": "corner fillet radius",
}

# The order they are read in: the two a rule fires on first, then the rest.
QUANTITY_ORDER: tuple[str, ...] = (
    "edge_distance_over_diameter",
    "hole_pitch_over_diameter",
    "hole_diameter_over_thickness",
    "hole_diameter_mm",
    "thickness_mm",
    "corner_fillet_radius_mm",
)

# Where the rules come from today. The machine is not an aviation machine: it
# reads whatever public record carries a failure and a number, and aviation is
# where that record is public (owner, 2026-09-20: say so, do not imply it).
SCOPE_TODAY = (
    "Right now the public record it reads is US aviation: airworthiness directives the FAA "
    "publishes after a part fails in service, and a US military materials handbook released "
    "for unlimited distribution. Nothing in the machine is tied to aviation. That is where the "
    "failures are written down in public."
)

# What happens to a part, in order. Not the same list as the panel's six
# stations: those are how a *fact* is made, and the panel owns them. These four
# are what the engine does to the geometry someone sends, and they are the spine
# of the counter in both versions.
STEPS: tuple[tuple[str, str, str], ...] = (
    ("measure", "Measure", "the real geometry, no assumptions"),
    ("judge", "Judge", "against rules that quote their source"),
    ("correct", "Correct", "arithmetic on parameters"),
    ("prove", "Prove", "re-measure the corrected file"),
)

# The same four steps as a job actually reports them. The engine tells the
# counter when it starts and when it delivers, and nothing in between, so
# correcting and proving are reported together at the end: a page that showed
# them ticking by one at a time would be inventing progress.
RUN_STEPS: tuple[tuple[str, str], ...] = (
    ("Received", "file checked on arrival"),
    ("Measure + judge", "real geometry, sourced rules"),
    ("Correct + prove", "reported together at the end"),
    ("Deliver", "report and corrected part"),
)

# One stamp per way a job can end: the four the engine produces (JobStatus) plus
# `error`, which only the counter produces and which is never a verdict on the
# part. `severity` says how the page should feel about it, so a skin can colour
# it without re-deciding what it means: `pass`, `note`, `fail`.
VERDICTS: dict[str, dict[str, str]] = {
    JobStatus.CLEAN: {
        "stamp": "PASSED",
        "line": "No rule was broken on the measured values.",
        "severity": "pass",
    },
    JobStatus.CORRECTED: {
        "stamp": "CORRECTED",
        "line": "Every violation was fixed and proven by re-measurement.",
        "severity": "pass",
    },
    JobStatus.UNCORRECTED: {
        "stamp": "REPORTED",
        "line": "Violations were found. The correction was refused, and the reason is below.",
        "severity": "note",
    },
    JobStatus.REFUSED: {
        "stamp": "REFUSED",
        "line": "This part could not be measured honestly, so no verdict was produced.",
        "severity": "fail",
    },
    "error": {
        "stamp": "NOT RUN",
        "line": (
            "The engine did not finish this job. Nothing was measured, so there is no "
            "verdict on your part."
        ),
        "severity": "fail",
    },
}

# The engine writes for an engineer reading a report; a page says the same thing
# in the words a visitor uses, and keeps the engine's exact sentence one click
# away. It never softens a refusal, only translates it. Matched on the engine's
# own reason text, first hit wins.
REFUSALS: tuple[tuple[str, str], ...] = (
    (
        "not vertical",
        "This part has a hole drilled from the side or at an angle. Version 1 measures "
        "flat plates with straight through-holes.",
    ),
    (
        "face type",
        "This part has a shaped face, such as a countersink or a curve, that version 1 "
        "does not measure.",
    ),
    (
        "hole depth",
        "This part has a hole that stops inside the material. Version 1 measures holes "
        "that go all the way through.",
    ),
    (
        "coaxial",
        "This part has a stepped or counterbored hole. Version 1 measures single-diameter "
        "through-holes.",
    ),
    (
        "plate assumption",
        "This part is not a flat plate lying flat. Version 1 measures plates.",
    ),
    ("separate parts", "This file holds more than one part. Send one part per file."),
    (
        "no 3d solid could be read",
        "This file could not be read as a 3D solid. Export it again as STEP (AP203 or "
        "AP214) from your CAD.",
    ),
    (
        "cannot classify",
        "A hole here breaks the outline of the plate or overlaps another hole, so it "
        "cannot be measured faithfully.",
    ),
    (
        "not a plain plate",
        "The outline is not a plain rectangle, so the part can be measured and reported "
        "but not rebuilt for correction.",
    ),
    (
        "plate too small",
        "Fixing this part would push a hole off the plate, so no correction was made.",
    ),
    (
        "rebuild is not faithful",
        "The part rebuilt from this file did not measure the same as the file, so "
        "correcting it would have corrected something else.",
    ),
)

REFUSAL_FALLBACK = (
    "This part is outside what version 1 can handle honestly, so it refused instead of guessing."
)

# What is left to do, once a job ended without a corrected file.
NEXT_STEP: dict[str, str] = {
    "refused": (
        "Nothing was measured, so nothing here is a verdict on your part. Send a flat plate "
        "with straight through-holes, or keep this link: the report appears here if the part "
        "is re-run on a later version."
    ),
    "reported": (
        "The findings above are real and measured. Only the automatic fix was held back, so "
        "you have the full report and the part you sent."
    ),
}

# The four roles a delivery can carry (the package is owned by scheinman.job).
FILE_LABELS: dict[str, str] = {
    "corrected_step": "Corrected part (.step)",
    "inspection_report": "Inspection report (.pdf)",
    "correction_report": "Correction report (.pdf)",
    "submitted_step": "The part you sent",
}


def series_options() -> list[dict[str, str]]:
    """The alloy choices, in the order the counter offers them.

    Built from the closed vocabulary, so a series added there and not described
    here stops the build instead of reaching a page unnamed.
    """
    missing = set(MATERIAL_SERIES) - set(SERIES_EXAMPLES)
    if missing:
        raise RuntimeError(
            f"{sorted(missing)} are declarable alloy series with no words for a visitor; "
            "add them to SERIES_EXAMPLES"
        )
    unknown = set(SERIES_ORDER) - set(MATERIAL_SERIES)
    if unknown:
        raise RuntimeError(f"{sorted(unknown)} is offered by the counter but is not a valid series")
    return [{"value": s, "examples": SERIES_EXAMPLES[s]} for s in SERIES_ORDER]


def as_dict() -> dict[str, object]:
    """Everything a page needs, as plain data."""
    return {
        "steps": [{"key": k, "name": n, "note": note} for k, n, note in STEPS],
        "series": series_options(),
        "defaultSeries": DEFAULT_SERIES,
        "loadings": [{"value": v, "label": label, "note": note} for v, label, note in LOADINGS],
        "verdicts": {str(k): v for k, v in VERDICTS.items()},
        "refusals": [[needle, plain] for needle, plain in REFUSALS],
        "refusalFallback": REFUSAL_FALLBACK,
        "nextStep": NEXT_STEP,
        "fileLabels": FILE_LABELS,
    }


def as_js() -> str:
    """The same data as the one script tag both versions read it from."""
    body = json.dumps(as_dict(), indent=2, ensure_ascii=False)
    # No user input reaches this; the escape is against a closing tag appearing
    # inside a sentence and ending the script element early.
    return f"<script>window.SCHEINMAN_WORDS = {body.replace('</', '<\\/')};</script>"
