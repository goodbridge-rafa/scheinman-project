"""One submitted part, start to finish: the unit of work the public counter runs.

A visitor hands over a STEP file and two declarations. This module measures it,
judges it, corrects it when it can, and writes a self-contained delivery folder:
the machine-readable result the dashboard renders, the reports, and the
corrected file. Nothing here reasons about the web, and nothing here guesses:
every path that cannot be walked honestly ends in a refusal that says why.
"""

from __future__ import annotations

import hashlib
import json
import re
import tempfile
from enum import StrEnum
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict

from scheinman.correction import Correction, CorrectionRefused, correct_until_clean
from scheinman.measure import UnmeasurableGeometryError, describe_plate, measure_step_file
from scheinman.paper import correction_pdf, inspection_pdf
from scheinman.parts import Hole, PartSpec, export_part
from scheinman.rules import publishable_rules
from scheinman.schemas import Measurement, Rule, UsageContext, Violation
from scheinman.verdict import evaluate

RESULT_FILENAME = "result.json"
# The submitted filename is untrusted input; it names files we then write.
_SAFE_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,59}")
# The rebuild must re-measure to the same numbers as the submitted file.
_REBUILD_TOLERANCE = 1e-6


class JobStatus(StrEnum):
    """Closed vocabulary. Every finished job is exactly one of these."""

    CLEAN = "clean"  # measured, judged, nothing broken
    CORRECTED = "corrected"  # violations found, fixed, proven by re-measurement
    UNCORRECTED = "uncorrected"  # violations found and reported; correction refused
    REFUSED = "refused"  # the part could not be measured honestly; no verdict


class JobResult(BaseModel):
    """Everything the dashboard shows, in one object. The files listed exist
    beside it in the same folder."""

    model_config = ConfigDict(frozen=True)

    job_key: str
    part_name: str
    status: JobStatus
    context: UsageContext
    measurements: tuple[Measurement, ...] = ()
    violations: tuple[Violation, ...] = ()
    corrections: tuple[Correction, ...] = ()
    proof: tuple[Measurement, ...] = ()
    correction_rounds: int = 0
    rules_evaluated: tuple[str, ...] = ()
    reason: str | None = None  # why refused, or why the correction was not made
    files: dict[str, str] = {}  # role -> filename in the delivery folder
    submitted_at: str | None = None  # stamped by the caller; this module has no clock


def job_key(step_bytes: bytes, context: UsageContext) -> str:
    """Identity of the work itself: same part plus same declarations, same key.

    Derived from the thing, never from the channel that delivered it, so a
    resubmission is recognised as already done instead of run twice.
    """
    digest = hashlib.sha256()
    digest.update(step_bytes)
    digest.update(b"\0")
    digest.update(f"{context.material_series}|{context.loading.value}".encode())
    return digest.hexdigest()[:16]


def _safe_part_name(name: str) -> str:
    """Refuse a hostile name instead of quietly rewriting it.

    Path(name).stem would have turned "../../etc/passwd" into "passwd" and
    carried on: contained, but the delivery would then claim a part name nobody
    submitted. At a trust boundary, silence is the bug.
    """
    stem = name
    for suffix in (".step", ".stp"):
        if stem.lower().endswith(suffix):
            stem = stem[: -len(suffix)]
            break
    if not _SAFE_NAME.fullmatch(stem):
        raise ValueError(
            f"part name {stem!r} is not a plain name: letters, digits, dot, dash and "
            "underscore only, up to 60 characters"
        )
    return stem


def _spec_from_file(step_path: Path, name: str, context: UsageContext) -> PartSpec:
    plate = describe_plate(step_path)
    return PartSpec(
        name=name,
        length=plate.length,
        width=plate.width,
        thickness=plate.thickness,
        holes=tuple(Hole(x, y, d) for x, y, d in plate.holes),
        context=context,
        corner_fillet_radius=plate.corner_fillet_radius,
        origin=plate.origin,
    )


def _rebuild_disagreement(original: list[Measurement], rebuilt: list[Measurement]) -> str | None:
    """Why the rebuilt part is not the submitted one, or None when it is.

    The corrector works on parameters read back from the file, so the read-back
    is only trustworthy if rebuilding from it re-measures to the same numbers.
    This is that proof; without it, a correction would silently be a correction
    of a different part.
    """
    a = {(m.feature_id, m.quantity): m.value for m in original}
    b = {(m.feature_id, m.quantity): m.value for m in rebuilt}
    missing = sorted(k for k in a if k not in b)
    extra = sorted(k for k in b if k not in a)
    if missing or extra:
        return (
            "the part rebuilt from the file's own parameters does not measure the same "
            f"features (missing {missing}, unexpected {extra}), so it is not the "
            "submitted part and correcting it would correct something else"
        )
    for key, value in a.items():
        if abs(value - b[key]) > _REBUILD_TOLERANCE * max(1.0, abs(value)):
            return (
                f"the part rebuilt from the file's own parameters measures "
                f"{key[1]} = {b[key]:.6f} at {key[0]} where the submitted file measures "
                f"{value:.6f}, so the rebuild is not faithful and no correction is made"
            )
    return None


def run_job(
    step_path: Path,
    context: UsageContext,
    outdir: Path,
    *,
    part_name: str | None = None,
    rules: list[Rule] | None = None,
    submitted_at: str | None = None,
) -> JobResult:
    """Run one submitted part and write its delivery folder.

    Re-running with the same part and the same declarations into the same
    folder returns the result already on disk instead of computing a second
    one: that is the command line's promise. The counter, on purpose, mints a
    new job for every upload (each is a line in the owner's archive) and hands
    the engine a fresh folder, so it never relies on this (audit 2026-09-02).
    """
    name = _safe_part_name(part_name or step_path.name)
    step_bytes = step_path.read_bytes()
    key = job_key(step_bytes, context)
    outdir.mkdir(parents=True, exist_ok=True)
    result_path = outdir / RESULT_FILENAME
    if result_path.exists():
        done = JobResult.model_validate_json(result_path.read_text(encoding="utf-8"))
        if done.job_key == key:
            return done

    # A delivered job is judged by the publishable rules only; a test fixture
    # is not an engineering fact and must never reach a visitor (audit 2026-09-02).
    rules = publishable_rules() if rules is None else rules
    files = {"submitted_step": f"{name}.step"}
    (outdir / files["submitted_step"]).write_bytes(step_bytes)

    evaluated = tuple(r.rule_id for r in rules)

    def _finish(status: JobStatus, **fields: Any) -> JobResult:
        """Write the delivery's result file and hand back what it says."""
        result = JobResult(
            job_key=key,
            part_name=name,
            status=status,
            context=context,
            rules_evaluated=evaluated,
            submitted_at=submitted_at,
            files=dict(files),
            **fields,
        )
        result_path.write_text(result.model_dump_json(indent=2) + "\n", encoding="utf-8")
        return result

    try:
        measurements = measure_step_file(step_path)
    except UnmeasurableGeometryError as refusal:
        return _finish(JobStatus.REFUSED, reason=str(refusal))

    violations = evaluate(context, measurements, rules)
    # The delivered report is a PDF: it is filed, printed and passed around
    # (owner, 2026-09-20). `scheinman.report` still renders the markdown the
    # repository's own demo packages and the tests read; both are built from
    # these same values, so neither retells the other.
    files["inspection_report"] = f"{name}-inspection.pdf"
    (outdir / files["inspection_report"]).write_bytes(
        inspection_pdf(
            part_name=name,
            context=context,
            measurements=measurements,
            violations=violations,
            rules_evaluated=rules,
            job_key=key,
            submitted_at=submitted_at or "not stated",
        )
    )

    if not violations:
        return _finish(JobStatus.CLEAN, measurements=tuple(measurements))

    found = {"measurements": tuple(measurements), "violations": tuple(violations)}
    with tempfile.TemporaryDirectory() as tmp:
        work = Path(tmp)
        try:
            spec = _spec_from_file(step_path, name, context)
        except UnmeasurableGeometryError as refusal:
            return _finish(JobStatus.UNCORRECTED, reason=str(refusal), **found)
        disagreement = _rebuild_disagreement(
            measurements, measure_step_file(export_part(spec, work))
        )
        if disagreement is not None:
            return _finish(JobStatus.UNCORRECTED, reason=disagreement, **found)
        try:
            corrected = correct_until_clean(spec, rules, work)
        except (CorrectionRefused, UnmeasurableGeometryError) as failure:
            # A deliberate refusal, in the corrector's or the measurer's own
            # words. Anything else is a real failure and must propagate: the
            # run fails, the counter is told, and the visitor reads "the engine
            # did not finish", never a verdict about the part (audit 2026-09-02).
            return _finish(JobStatus.UNCORRECTED, reason=str(failure), **found)
        files["corrected_step"] = corrected.step_path.name
        (outdir / files["corrected_step"]).write_bytes(corrected.step_path.read_bytes())

    files["correction_report"] = f"{name}-correction.pdf"
    (outdir / files["correction_report"]).write_bytes(
        correction_pdf(
            part_name=name,
            context=context,
            before=violations,
            result=corrected,
            rules_evaluated=rules,
            submitted_spec=spec,
            job_key=key,
            submitted_at=submitted_at or "not stated",
        )
    )
    return _finish(
        JobStatus.CORRECTED,
        corrections=corrected.corrections,
        proof=corrected.proof,
        correction_rounds=corrected.rounds,
        **found,
    )


def main(argv: list[str] | None = None) -> int:
    """Command line the engine workflow calls: one part in, one folder out."""
    import argparse

    parser = argparse.ArgumentParser(prog="python -m scheinman.job", description=__doc__)
    parser.add_argument("step", type=Path, help="the submitted .step file")
    parser.add_argument("outdir", type=Path, help="folder to write the delivery into")
    parser.add_argument("--material-series", required=True, help="alloy series, e.g. 7xxx")
    parser.add_argument("--loading", required=True, choices=["cyclic", "static"])
    parser.add_argument("--part-name", default=None)
    parser.add_argument("--submitted-at", default=None, help="timestamp to stamp on the result")
    args = parser.parse_args(argv)

    context = UsageContext(material_series=args.material_series, loading=args.loading)
    result = run_job(
        args.step,
        context,
        args.outdir,
        part_name=args.part_name,
        submitted_at=args.submitted_at,
    )
    print(json.dumps({"status": result.status.value, "job_key": result.job_key}))
    # A refusal is a finished job, not a crash: the counter shows the reason.
    return 0


if __name__ == "__main__":  # pragma: no cover - thin CLI wrapper
    raise SystemExit(main())
