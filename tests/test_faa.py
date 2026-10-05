"""Collector logic without the network: parsing, union, idempotency."""

import time
from pathlib import Path

import pytest

from scheinman import faa
from scheinman.faa import AdRecord, collect, load_index, parse_results, union

SAMPLE = {
    "count": 2,
    "total_pages": 1,
    "results": [
        {
            "document_number": "E7-9396",
            "title": "Airworthiness Directives; Boeing Model 747-400 Series Airplanes",
            "publication_date": "2007-05-17",
            "citation": "72 FR 27729",
            "raw_text_url": "https://example.invalid/E7-9396.txt",
        },
        {
            "document_number": "2026-17553",
            "title": "Airworthiness Directives; The Boeing Company Airplanes",
            "publication_date": "2026-08-27",
            "citation": None,
            "raw_text_url": "https://example.invalid/2026-17553.txt",
        },
        {
            "document_number": "NO-TEXT",
            "title": "Entry without raw text is skipped",
            "publication_date": "2020-01-01",
            "citation": None,
            "raw_text_url": None,
        },
    ],
}


def test_parse_skips_entries_without_raw_text() -> None:
    records = parse_results(SAMPLE, "q1")
    assert [r.document_number for r in records] == ["E7-9396", "2026-17553"]
    assert records[0].found_by == ("q1",)


def test_union_dedupes_and_remembers_every_query() -> None:
    a = parse_results(SAMPLE, "q1")
    b = parse_results(SAMPLE, "q2")
    merged = union([a, b])
    assert len(merged) == 2
    assert merged["E7-9396"].found_by == ("q1", "q2")


def test_collect_is_idempotent_and_merges_index(tmp_path: Path, monkeypatch: object) -> None:
    fetched: list[str] = []

    def fake_fetch(url: str) -> bytes:
        fetched.append(url)
        return b"AD BODY"

    import pytest

    assert isinstance(monkeypatch, pytest.MonkeyPatch)
    monkeypatch.setattr(faa, "_fetch", fake_fetch)
    records = union([parse_results(SAMPLE, "q1")])

    downloaded, already = collect(tmp_path, records)
    assert (downloaded, already) == (2, 0)
    downloaded, already = collect(tmp_path, records)
    assert (downloaded, already) == (0, 2), "second run must say 'already have', never re-fetch"
    assert len(fetched) == 2

    index = load_index(tmp_path)
    assert set(index) == {"E7-9396", "2026-17553"}
    assert (tmp_path / "E7-9396.txt").read_bytes() == b"AD BODY"


def test_record_is_immutable() -> None:
    # Audit 2026-08-30: the old try/except swallowed its own AssertionError and
    # this test could never fail. pytest.raises cannot be swallowed.
    import pytest
    from pydantic import ValidationError

    rec = parse_results(SAMPLE, "q")[0]
    assert isinstance(rec, AdRecord)
    with pytest.raises(ValidationError):
        rec.title = "x"


def test_search_all_default_includes_the_british_spelling_wave() -> None:
    # Deep audit 2026-09-01: the default was the v1 set that provably missed
    # AD 2019-18045 ("aluminium"); the default must be the full union.
    import inspect

    from scheinman.faa import ALL_QUERIES, search_all

    default = inspect.signature(search_all).parameters["queries"].default
    assert default == ALL_QUERIES
    assert any("aluminium" in q for q in default)


def test_fetch_does_not_sleep_after_the_final_failure(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    import urllib.request

    from scheinman import faa

    sleeps: list[float] = []
    monkeypatch.setattr(time, "sleep", lambda s: sleeps.append(s))

    def boom(url: str, timeout: float = 0) -> None:
        raise TimeoutError("no route")

    monkeypatch.setattr(urllib.request, "urlopen", boom)
    with pytest.raises(RuntimeError, match="fetch failed"):
        faa._fetch("https://example.invalid/x")
    assert len(sleeps) == faa._RETRIES - 1, "backoff must sit between attempts, not after the last"


def test_fetch_does_not_retry_a_plain_404(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    import io
    import urllib.error
    import urllib.request

    from scheinman import faa

    calls: list[str] = []
    monkeypatch.setattr(time, "sleep", lambda s: None)

    def gone(url: str, timeout: float = 0) -> None:
        calls.append(url)
        raise urllib.error.HTTPError(url, 404, "Not Found", None, io.BytesIO(b""))  # type: ignore[arg-type]

    monkeypatch.setattr(urllib.request, "urlopen", gone)
    with pytest.raises(RuntimeError, match="404"):
        faa._fetch("https://example.invalid/gone")
    assert len(calls) == 1, "a definitive 4xx answer is final; retrying it is noise"


def test_collect_never_shrinks_found_by_history(tmp_path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    from scheinman import faa
    from scheinman.faa import AdRecord, collect, load_index

    monkeypatch.setattr(faa, "_fetch", lambda url: b"text")
    monkeypatch.setattr(time, "sleep", lambda s: None)
    rec_two = AdRecord(
        document_number="00-1",
        title="t",
        publication_date="2000-01-01",
        citation=None,
        raw_text_url="u",
        found_by=("q1", "q2"),
    )
    collect(tmp_path, {"00-1": rec_two})
    rec_one = rec_two.model_copy(update={"found_by": ("q1",)})
    collect(tmp_path, {"00-1": rec_one})
    assert load_index(tmp_path)["00-1"]["found_by"] == ["q1", "q2"]


def test_collect_marks_a_failed_fetch_and_keeps_going_then_clears_it(tmp_path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    from scheinman import faa
    from scheinman.faa import AdRecord, collect, load_index

    monkeypatch.setattr(time, "sleep", lambda s: None)

    def flaky(url: str) -> bytes:
        if "bad" in url:
            raise RuntimeError("fetch failed after 3 attempts: " + url)
        return b"text"

    monkeypatch.setattr(faa, "_fetch", flaky)
    records = {
        "00-1": AdRecord(
            document_number="00-1",
            title="t",
            publication_date="d",
            citation=None,
            raw_text_url="https://x/bad",
            found_by=("q",),
        ),
        "00-2": AdRecord(
            document_number="00-2",
            title="t",
            publication_date="d",
            citation=None,
            raw_text_url="https://x/ok",
            found_by=("q",),
        ),
    }
    downloaded, _ = collect(tmp_path, records)
    index = load_index(tmp_path)
    assert downloaded == 1 and "fetch_error" in index["00-1"]
    monkeypatch.setattr(faa, "_fetch", lambda url: b"text")
    collect(tmp_path, records)
    assert "fetch_error" not in load_index(tmp_path)["00-1"]
