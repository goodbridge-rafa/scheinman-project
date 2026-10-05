"""The engine's side of the wire: fetch one job's part, run it, hand it back.

This is what the analyze workflow runs. It talks to the counter over plain
HTTP with the standard library: an explicit timeout, an explicit number of
attempts, and a defined behavior when the last attempt fails (raise, so the
workflow run goes red and the failure is visible instead of silent).
"""

from __future__ import annotations

import base64
import json
import time
import urllib.error
import urllib.request
from pathlib import Path

from scheinman.job import RESULT_FILENAME, JobResult, run_job
from scheinman.schemas import Loading, UsageContext

TIMEOUT_SECONDS = 30.0
ATTEMPTS = 3
BACKOFF_SECONDS = 2.0
# The delivery is small (reports in kilobytes, a plate STEP in tens of them);
# a part that produced more than this is not something to push through a
# callback, and the guard says so instead of timing out mysteriously.
MAX_CALLBACK_BYTES = 20 * 1024 * 1024


class DeliveryError(RuntimeError):
    """The counter could not be reached, or refused what the engine sent."""


def _request(
    url: str,
    *,
    secret: str,
    data: bytes | None = None,
    content_type: str | None = None,
    opener: object = None,
) -> bytes:
    """One call, retried a fixed number of times, never forever."""
    headers = {"x-scheinman-engine": secret, "user-agent": "scheinman-engine"}
    if content_type:
        headers["content-type"] = content_type
    request = urllib.request.Request(url, data=data, headers=headers)
    send = opener if opener is not None else urllib.request.urlopen
    last: Exception | None = None
    for attempt in range(ATTEMPTS):
        try:
            with send(request, timeout=TIMEOUT_SECONDS) as response:  # type: ignore[operator]
                return bytes(response.read())
        except urllib.error.HTTPError as error:
            # The counter answered: a 4xx is a decision, not a hiccup, so it is
            # not retried. Only its own failures (5xx) are worth another try.
            if error.code < 500:
                raise DeliveryError(
                    f"{url} answered {error.code} and will not answer better"
                ) from error
            last = error
        except OSError as error:
            last = error
        if attempt < ATTEMPTS - 1:
            time.sleep(BACKOFF_SECONDS * (attempt + 1))
    raise DeliveryError(f"{url} did not answer after {ATTEMPTS} attempts: {last}")


def fetch_part(
    base_url: str, job_id: str, secret: str, directory: Path, opener: object = None
) -> Path:
    """Bring the submitted part down to where the engine can measure it."""
    body = _request(f"{base_url}/api/jobs/{job_id}/part", secret=secret, opener=opener)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / "submitted.step"
    path.write_bytes(body)
    return path


def announce_running(
    base_url: str, job_id: str, secret: str, run_id: str, opener: object = None
) -> None:
    """Tell the counter the job left the queue, so the page stops saying queued."""
    _request(
        f"{base_url}/api/jobs/{job_id}/callback",
        secret=secret,
        data=json.dumps({"status": "running", "run_id": run_id}).encode(),
        content_type="application/json",
        opener=opener,
    )


def delivery_payload(outdir: Path) -> dict[str, object]:
    """The finished job, packed for the counter: the result and its files."""
    result = JobResult.model_validate_json((outdir / RESULT_FILENAME).read_text(encoding="utf-8"))
    files: dict[str, str] = {}
    total = 0
    for role, filename in result.files.items():
        raw = (outdir / filename).read_bytes()
        total += len(raw)
        if total > MAX_CALLBACK_BYTES:
            raise DeliveryError(
                f"this delivery is over {MAX_CALLBACK_BYTES // (1024 * 1024)} MB, which is more "
                "than the counter takes in one callback"
            )
        files[role] = base64.b64encode(raw).decode("ascii")
    return {
        "status": result.status.value,
        "result": json.loads(result.model_dump_json()),
        "files": files,
    }


def report_failure(
    base_url: str, job_id: str, secret: str, reason: str, opener: object = None
) -> None:
    """Say the engine broke, so the page stops spinning forever.

    A run that dies without this leaves the visitor watching a queue that will
    never move: silence is the worst possible answer (.claude/rules/automacao.md).
    """
    _request(
        f"{base_url}/api/jobs/{job_id}/callback",
        secret=secret,
        data=json.dumps({"status": "error", "reason": reason}).encode(),
        content_type="application/json",
        opener=opener,
    )


def deliver(base_url: str, job_id: str, secret: str, outdir: Path, opener: object = None) -> None:
    _request(
        f"{base_url}/api/jobs/{job_id}/callback",
        secret=secret,
        data=json.dumps(delivery_payload(outdir)).encode(),
        content_type="application/json",
        opener=opener,
    )


def main(argv: list[str] | None = None, opener: object = None) -> int:
    """One job, start to finish, as the workflow runs it.

    `opener` is the same hook every helper takes: tests hand in a scripted
    counter, the workflow hands in nothing and talks to the real one."""
    import argparse
    import os
    import tempfile

    parser = argparse.ArgumentParser(prog="python -m scheinman.deliver", description=__doc__)
    parser.add_argument("--base-url", required=True, help="where the counter lives")
    parser.add_argument("--job-id", required=True)
    parser.add_argument("--run-id", default="", help="this workflow run, for the counter's log")
    parser.add_argument("--outdir", type=Path, default=Path("delivery"))
    parser.add_argument(
        "--report-failure",
        default=None,
        help="tell the counter this run broke, instead of running a part",
    )
    args = parser.parse_args(argv)

    secret = os.environ.get("ENGINE_SECRET", "")
    if not secret:
        raise SystemExit("ENGINE_SECRET is not set; the counter would refuse this engine")
    base = args.base_url.rstrip("/")

    if args.report_failure:
        report_failure(base, args.job_id, secret, args.report_failure, opener=opener)
        print(json.dumps({"status": "error", "job": args.job_id}))
        return 0

    announce_running(base, args.job_id, secret, args.run_id, opener=opener)
    with tempfile.TemporaryDirectory() as tmp:
        part = fetch_part(base, args.job_id, secret, Path(tmp), opener=opener)
        job = json.loads(
            _request(f"{base}/api/jobs/{args.job_id}", secret=secret, opener=opener).decode("utf-8")
        )
        context = UsageContext(
            material_series=job["material_series"], loading=Loading(job["loading"])
        )
        result = run_job(
            part,
            context,
            args.outdir,
            part_name=job["part_name"],
            submitted_at=job.get("created_at"),
        )
    deliver(base, args.job_id, secret, args.outdir, opener=opener)
    print(json.dumps({"status": result.status.value, "job": args.job_id}))
    return 0


if __name__ == "__main__":  # pragma: no cover - thin CLI wrapper
    raise SystemExit(main())
