"""The wire between the engine and the counter: explicit timeout, explicit
attempts, defined behavior on the last failure (.claude/rules/qualidade.md).

No network here: a fake opener plays the counter, so these tests pin the retry
policy itself rather than hoping the internet behaves.
"""

from __future__ import annotations

import base64
import json
import urllib.error
from pathlib import Path
from typing import Any

import pytest

from scheinman.deliver import (
    ATTEMPTS,
    DeliveryError,
    _request,
    deliver,
    delivery_payload,
    fetch_part,
    report_failure,
)
from scheinman.job import run_job
from scheinman.parts import export_part, stage1_parts
from scheinman.schemas import Loading, UsageContext


class _Answer:
    def __init__(self, body: bytes) -> None:
        self._body = body

    def read(self) -> bytes:
        return self._body

    def __enter__(self) -> _Answer:
        return self

    def __exit__(self, *_: object) -> None:
        return None


class _Counter:
    """A fake counter that answers a scripted sequence and records the calls."""

    def __init__(self, *answers: Any) -> None:
        self.answers = list(answers)
        self.calls: list[Any] = []

    def __call__(self, request: Any, timeout: float | None = None) -> _Answer:
        self.calls.append((request, timeout))
        answer = self.answers.pop(0) if self.answers else _Answer(b"ok")
        if isinstance(answer, Exception):
            raise answer
        return answer


def _http_error(code: int) -> urllib.error.HTTPError:
    return urllib.error.HTTPError("http://counter/x", code, "boom", {}, None)  # type: ignore[arg-type]


def test_the_engine_identifies_itself_and_sets_a_timeout() -> None:
    counter = _Counter(_Answer(b"body"))
    assert _request("http://counter/x", secret="s3cr3t", opener=counter) == b"body"
    request, timeout = counter.calls[0]
    assert request.get_header("X-scheinman-engine") == "s3cr3t"
    assert timeout and timeout > 0


def test_a_counter_failure_is_retried_a_fixed_number_of_times(monkeypatch: Any) -> None:
    monkeypatch.setattr("scheinman.deliver.time.sleep", lambda _: None)
    counter = _Counter(_http_error(503), _http_error(503), _Answer(b"finally"))
    assert _request("http://counter/x", secret="s", opener=counter) == b"finally"
    assert len(counter.calls) == 3


def test_a_refusal_is_a_decision_and_is_never_retried(monkeypatch: Any) -> None:
    monkeypatch.setattr("scheinman.deliver.time.sleep", lambda _: None)
    counter = _Counter(_http_error(401))
    with pytest.raises(DeliveryError, match="401"):
        _request("http://counter/x", secret="wrong", opener=counter)
    assert len(counter.calls) == 1, "a 401 will not become a 200 by asking again"


def test_giving_up_is_loud_not_silent(monkeypatch: Any) -> None:
    monkeypatch.setattr("scheinman.deliver.time.sleep", lambda _: None)
    counter = _Counter(*[OSError("network down")] * ATTEMPTS)
    with pytest.raises(DeliveryError, match=f"{ATTEMPTS} attempts"):
        _request("http://counter/x", secret="s", opener=counter)


def test_the_part_arrives_as_bytes_on_disk(tmp_path: Path) -> None:
    counter = _Counter(_Answer(b"ISO-10303-21;\n"))
    path = fetch_part("http://counter", "a" * 32, "s", tmp_path, opener=counter)
    assert path.read_bytes() == b"ISO-10303-21;\n"


def _finished_job(tmp_path: Path) -> Path:
    spec = next(s for s in stage1_parts() if s.name == "plate-edge-close")
    step = export_part(spec, tmp_path)
    out = tmp_path / "delivery"
    run_job(step, spec.context, out, part_name=spec.name)
    return out


def test_the_delivery_carries_the_result_and_every_file(tmp_path: Path) -> None:
    payload = delivery_payload(_finished_job(tmp_path))
    assert payload["status"] == "corrected"
    files = payload["files"]
    assert isinstance(files, dict)
    assert {"submitted_step", "inspection_report", "correction_report", "corrected_step"} <= set(
        files
    )
    # Real bytes, decodable on the other side, not a description of them.
    corrected = base64.b64decode(files["corrected_step"])
    assert corrected.startswith(b"ISO-10303-21")
    result = payload["result"]
    assert isinstance(result, dict)
    assert result["violations"] and result["proof"]


def test_an_oversized_delivery_is_refused_before_it_is_sent(
    tmp_path: Path, monkeypatch: Any
) -> None:
    monkeypatch.setattr("scheinman.deliver.MAX_CALLBACK_BYTES", 10)
    with pytest.raises(DeliveryError, match="more than the counter takes"):
        delivery_payload(_finished_job(tmp_path))


def test_the_callback_sends_json_the_counter_can_read(tmp_path: Path) -> None:
    counter = _Counter(_Answer(b'{"ok":true}'))
    deliver("http://counter", "b" * 32, "s", _finished_job(tmp_path), opener=counter)
    request, _ = counter.calls[0]
    assert request.full_url.endswith("/callback")
    body = json.loads(request.data)
    assert body["status"] == "corrected"
    assert body["result"]["part_name"] == "plate-edge-close"


def test_a_broken_run_tells_the_counter_instead_of_leaving_the_page_spinning() -> None:
    counter = _Counter(_Answer(b'{"ok":true}'))
    report_failure("http://counter", "c" * 32, "s", "the engine run failed", opener=counter)
    request, _ = counter.calls[0]
    body = json.loads(request.data)
    assert body == {"status": "error", "reason": "the engine run failed"}


def test_the_workflows_failure_step_needs_nothing_the_failure_could_have_broken() -> None:
    # Audit 2026-09-02: the failure report used to run through uv and the
    # project's own venv, the very things whose failure it must report. It is
    # plain curl now, runs on timeout too, and posts the same body the module's
    # report_failure() posts, so the counter cannot tell them apart.
    workflow = (
        Path(__file__).resolve().parents[1] / ".github" / "workflows" / "analyze.yml"
    ).read_text()
    assert "if: failure() || cancelled()" in workflow
    assert "curl --fail" in workflow
    assert "/api/jobs/$JOB_ID/callback" in workflow
    assert "x-scheinman-engine: $ENGINE_SECRET" in workflow
    assert '\\"status\\":\\"error\\"' in workflow
    assert (
        "uv run"
        not in workflow.split("Tell the counter if the engine broke")[1].split("- name:")[0]
    )
    assert "python -m scheinman.deliver" in workflow  # the happy path still is the module


def test_the_context_the_engine_runs_is_the_one_the_visitor_declared() -> None:
    # The engine never invents a context: it reads back what the counter stored,
    # and the closed vocabulary refuses anything else at construction.
    context = UsageContext(material_series="7xxx", loading=Loading("cyclic"))
    assert context.loading is Loading.CYCLIC
    with pytest.raises(ValueError):
        UsageContext(material_series="7075-T6", loading=Loading.CYCLIC)


def test_main_runs_a_job_end_to_end_against_a_scripted_counter(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    # Audit 2026-09-02: the command the workflow actually runs was the
    # one piece with no test. The counter is scripted; the engine is real.
    from scheinman.deliver import main
    from scheinman.parts import export_part, stage1_parts

    spec = next(s for s in stage1_parts() if s.name == "plate-clean")
    part_bytes = export_part(spec, tmp_path).read_bytes()
    job = {
        "material_series": "7xxx",
        "loading": "cyclic",
        "part_name": "plate-clean",
        "created_at": "2026-09-02T12:00:00Z",
    }
    counter = _Counter(
        _Answer(b'{"ok":true}'),  # running
        _Answer(part_bytes),  # the part
        _Answer(json.dumps(job).encode()),  # the job record
        _Answer(b'{"ok":true}'),  # the delivery
    )
    monkeypatch.setenv("ENGINE_SECRET", "s")
    code = main(
        [
            "--base-url",
            "http://counter",
            "--job-id",
            "d" * 32,
            "--run-id",
            "77",
            "--outdir",
            str(tmp_path / "delivery"),
        ],
        opener=counter,
    )
    assert code == 0
    assert json.loads(capsys.readouterr().out) == {"status": "clean", "job": "d" * 32}
    urls = [request.full_url for request, _ in counter.calls]
    assert urls == [
        "http://counter/api/jobs/" + "d" * 32 + "/callback",
        "http://counter/api/jobs/" + "d" * 32 + "/part",
        "http://counter/api/jobs/" + "d" * 32,
        "http://counter/api/jobs/" + "d" * 32 + "/callback",
    ]
    first = json.loads(counter.calls[0][0].data)
    assert first == {"status": "running", "run_id": "77"}
    last = json.loads(counter.calls[-1][0].data)
    assert last["status"] == "clean"
    assert set(last["files"]) >= {"submitted_step", "inspection_report"}
    assert last["result"]["part_name"] == "plate-clean"
