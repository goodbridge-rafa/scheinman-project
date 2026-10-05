"""Lot selection, batch parsing and per-document merging for AD extraction.

The agents read; this module judges and accounts. The material series is
derived here, in code, from the alloy string the document itself states,
so no extractor ever classifies a series by judgment.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict

from scheinman.extraction import (
    ExtractedField,
    FormField,
    MergeResult,
    load_extractor_output,
    merge,
)


def series_from_alloy(alloy_as_stated: str) -> str:
    """Deterministic: '7075-T6' -> '7xxx'; '7000 series aluminum' -> '7xxx'.

    First 4-digit [2-8]xxx number wins. Known limit: a string that names a spec
    number before the alloy ('per AMS 4045, alloy 7075') would classify by the
    spec number; the extraction form asks for the alloy designation alone, so
    such a value should not reach here as an agreed fact.
    """
    m = re.search(r"\b([2-8])\d{3}\b", alloy_as_stated)
    if m:
        return f"{m.group(1)}xxx"
    return "unknown"


def select_lot(index: dict[str, dict[str, Any]], query_substring: str) -> list[str]:
    """Document numbers whose finding queries contain the substring; skips fetch errors."""
    out = []
    for number, entry in sorted(index.items()):
        if entry.get("fetch_error"):
            continue
        if any(query_substring in q for q in entry.get("found_by", [])):
            out.append(number)
    return out


def batches(items: list[str], size: int) -> list[list[str]]:
    return [items[i : i + size] for i in range(0, len(items), size)]


def parse_batch_output(raw: dict[str, Any]) -> dict[str, list[ExtractedField]]:
    ads = raw.get("ads")
    if not isinstance(ads, dict):
        raise ValueError("batch output must carry an 'ads' object keyed by document number")
    return {
        str(number): load_extractor_output(payload if isinstance(payload, dict) else {})
        for number, payload in ads.items()
    }


class LotStats(BaseModel):
    model_config = ConfigDict(frozen=True)

    documents: int
    facts: int
    blanks: int

    @property
    def divergence_rate(self) -> float:
        total = self.facts + self.blanks
        return self.blanks / total if total else 0.0


def merge_lot(
    form: list[FormField],
    a_by_doc: dict[str, list[ExtractedField]],
    b_by_doc: dict[str, list[ExtractedField]],
) -> tuple[dict[str, MergeResult], LotStats]:
    results: dict[str, MergeResult] = {}
    facts = 0
    blanks = 0
    for number in sorted(set(a_by_doc) | set(b_by_doc)):
        result = merge(form, a_by_doc.get(number, []), b_by_doc.get(number, []))
        results[number] = result
        facts += len(result.facts)
        blanks += len(result.blanks)
    return results, LotStats(documents=len(results), facts=facts, blanks=blanks)


def lot_payload(results: dict[str, MergeResult], stats: LotStats) -> dict[str, object]:
    """The shape of a published merged.json, with one owner.

    Health audit 2026-09-01: this shape was written here and rebuilt, by hand,
    inside the replay test. Two copies of a shipped artifact's shape means a
    change to one of them passes the test that was supposed to catch it.
    """
    return {
        "stats": stats.model_dump() | {"divergence_rate": round(stats.divergence_rate, 4)},
        "documents": {n: json.loads(r.model_dump_json()) for n, r in results.items()},
    }


def save_lot(dest: Path, results: dict[str, MergeResult], stats: LotStats) -> None:
    dest.mkdir(parents=True, exist_ok=True)
    (dest / "merged.json").write_text(
        json.dumps(lot_payload(results, stats), indent=1, ensure_ascii=False, sort_keys=True),
        encoding="utf-8",
    )


def build_batch_prompt(persona_path: str, form_path: str, ad_paths: list[str]) -> str:
    """Render the extractor order verbatim from the batch spec.

    Exists because of lesson 006: a hand-typed file list once carried invented
    document numbers. The order an extractor receives is generated from the
    spec by this function and used verbatim, never retyped.
    """
    root = Path(__file__).resolve().parents[2]
    numbers = [p.rsplit("/", 1)[-1].removesuffix(".txt") for p in ad_paths]
    files = ", ".join(f"{root}/{p}" for p in ad_paths)
    example = numbers[0]
    return (
        f"Read {root}/{persona_path} and adopt it as your operating rules "
        '(where the rules say "page", report 1). '
        f"Read {root}/{form_path}: it is your per-document extraction form; "
        "obey its closed vocabularies exactly (an answer outside the allowed list is a defect; "
        "'none_stated' is an explicit answer; null only when unreadable). "
        f"Then Read each of these {len(ad_paths)} FAA Airworthiness Directive text files in "
        f"full and fill the form for each: {files}. "
        "Your final message must be ONLY strict JSON of the shape "
        f'{{"ads": {{"{example}": {{"fields": [...]}}, ...}}}} with one entry per document '
        "number (the filename without .txt), nothing else."
    )


def validate_against_spec(
    parsed: dict[str, list[ExtractedField]], allowed_numbers: set[str]
) -> tuple[dict[str, list[ExtractedField]], list[str], list[str]]:
    """Boundary guard (lesson 006): answers for documents outside the batch spec
    are rejected, and documents the readers never answered are named too —
    an absence that hides is as dangerous as an invention (audit 2026-09-01)."""
    kept = {n: fields for n, fields in parsed.items() if n in allowed_numbers}
    rejected = sorted(set(parsed) - allowed_numbers)
    missing = sorted(allowed_numbers - set(parsed))
    return kept, rejected, missing
