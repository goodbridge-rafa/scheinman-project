"""Collector for FAA Airworthiness Directives via the Federal Register API.

The compatible ingestion route locked in the source map: the documented, keyless
Federal Register API for the AD body text, with the raw document stored forever
in the vault. The collector is idempotent: the stable key is the Federal
Register document number, an existing file is never fetched twice, and re-runs
say "already have" instead of duplicating.
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict

FR_API = "https://www.federalregister.gov/api/v1/documents.json"

# Union of targeted searches; overlap is expected and removed by document number.
V1_QUERIES: tuple[str, ...] = (
    "airworthiness directive aluminum fatigue cracking",
    "fatigue cracking spar",
    "fatigue cracking fastener holes",
    "fatigue cracking fuselage skin",
)

# Second wave (2026-08-30): alloy-designation searches, plus the British
# spelling — the first wave's "aluminum" substring missed AD 2019-18045, an
# Airbus AD that only ever writes "aluminium".
V2_QUERIES: tuple[str, ...] = (
    "airworthiness directive 7075 aluminum",
    "airworthiness directive 2024 aluminum cracking",
    "airworthiness directive aluminium cracking",
    "stress corrosion cracking aluminum alloy",
)

ALL_QUERIES: tuple[str, ...] = V1_QUERIES + V2_QUERIES

_TIMEOUT_S = 30
_RETRIES = 3
_PAUSE_S = 0.15  # polite pacing between requests


class AdRecord(BaseModel):
    model_config = ConfigDict(frozen=True)

    document_number: str
    title: str
    publication_date: str
    citation: str | None
    raw_text_url: str
    found_by: tuple[str, ...]  # which queries surfaced it


def _fetch(url: str) -> bytes:
    last: Exception | None = None
    for attempt in range(_RETRIES):
        try:
            with urllib.request.urlopen(url, timeout=_TIMEOUT_S) as resp:
                return bytes(resp.read())
        except urllib.error.HTTPError as exc:
            # A definitive client-side answer is final; only rate limiting and
            # server errors deserve a retry (deep audit 2026-09-01).
            if exc.code < 500 and exc.code != 429:
                raise RuntimeError(f"fetch failed ({exc.code}) with no retry: {url}") from exc
            last = exc
        except Exception as exc:  # noqa: BLE001 - retried, then surfaced
            last = exc
        if attempt < _RETRIES - 1:
            time.sleep(2**attempt)
    raise RuntimeError(f"fetch failed after {_RETRIES} attempts: {url}") from last


def _search_url(query: str, page: int) -> str:
    params = {
        "conditions[term]": query,
        "conditions[type][]": "RULE",
        "conditions[agencies][]": "federal-aviation-administration",
        "conditions[publication_date][gte]": "2000-01-01",
        "per_page": "100",
        "page": str(page),
        "fields[]": ["document_number", "title", "publication_date", "citation", "raw_text_url"],
    }
    return FR_API + "?" + urllib.parse.urlencode(params, doseq=True)


def parse_results(payload: dict[str, Any], query: str) -> list[AdRecord]:
    out: list[AdRecord] = []
    for item in payload.get("results", []) or []:
        if not item.get("raw_text_url"):
            continue
        out.append(
            AdRecord(
                document_number=str(item["document_number"]),
                title=str(item.get("title", "")),
                publication_date=str(item.get("publication_date", "")),
                citation=item.get("citation"),
                raw_text_url=str(item["raw_text_url"]),
                found_by=(query,),
            )
        )
    return out


def union(batches: list[list[AdRecord]]) -> dict[str, AdRecord]:
    """Dedupe by document number, remembering every query that found each record."""
    merged: dict[str, AdRecord] = {}
    for batch in batches:
        for rec in batch:
            existing = merged.get(rec.document_number)
            if existing is None:
                merged[rec.document_number] = rec
            else:
                found = tuple(dict.fromkeys(existing.found_by + rec.found_by))
                merged[rec.document_number] = existing.model_copy(update={"found_by": found})
    return merged


def search_all(queries: tuple[str, ...] = ALL_QUERIES) -> dict[str, AdRecord]:
    batches: list[list[AdRecord]] = []
    for query in queries:
        page = 1
        while True:
            payload = json.loads(_fetch(_search_url(query, page)).decode("utf-8"))
            records = parse_results(payload, query)
            batches.append(records)
            total_pages = int(payload.get("total_pages", 1))
            # Stop on the declared last page or a truly empty page; a page whose
            # results were all filtered (no raw_text_url) must not end the query
            # (audit 2026-08-30: silent truncation of the collection).
            raw_count = len(payload.get("results", []) or [])
            if page >= total_pages or raw_count == 0:
                break
            page += 1
            time.sleep(_PAUSE_S)
    return union(batches)


def load_index(dest: Path) -> dict[str, dict[str, Any]]:
    index_path = dest / "index.json"
    if index_path.exists():
        data = json.loads(index_path.read_text(encoding="utf-8"))
        return {str(k): dict(v) for k, v in data.items()}
    return {}


def collect(dest: Path, records: dict[str, AdRecord]) -> tuple[int, int]:
    """Download raw texts into dest. Returns (downloaded, already_had)."""
    dest.mkdir(parents=True, exist_ok=True)
    index = load_index(dest)
    downloaded = 0
    already = 0
    for number, rec in sorted(records.items()):
        target = dest / f"{number}.txt"
        entry = index.get(number, {})
        previous_found_by = tuple(entry.get("found_by", ()))
        entry.update(rec.model_dump())
        # A run with fewer queries must never shrink the recorded history of
        # which queries found a document (audit 2026-08-30).
        entry["found_by"] = list(dict.fromkeys(previous_found_by + rec.found_by))
        if target.exists():
            already += 1
            entry.pop("fetch_error", None)
        else:
            try:
                target.write_bytes(_fetch(rec.raw_text_url))
                downloaded += 1
                entry.pop("fetch_error", None)
            except RuntimeError as exc:
                # One missing document never kills the batch: mark it, keep going.
                entry["fetch_error"] = str(exc)
            time.sleep(_PAUSE_S)
        index[number] = entry
    (dest / "index.json").write_text(
        json.dumps(index, indent=1, sort_keys=True, ensure_ascii=False), encoding="utf-8"
    )
    return downloaded, already


def main() -> None:
    dest = Path("data/raw/ads")
    records = search_all(ALL_QUERIES)
    print(f"union: {len(records)} unique documents across {len(ALL_QUERIES)} queries")
    downloaded, already = collect(dest, records)
    errors = sum(1 for v in load_index(dest).values() if v.get("fetch_error"))
    print(f"downloaded: {downloaded} · already had: {already} · fetch errors: {errors}")
    print(f"vault: {dest}")


if __name__ == "__main__":
    main()
