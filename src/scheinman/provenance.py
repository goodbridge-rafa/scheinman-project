"""Measure, never claim: does every excerpt occur in the stored record?

The evidence page used to say "each with its verbatim excerpt" with nothing
behind the sentence (audit 2026-09-02). This module checks every
double-blind AD fact and every rule anchor against the text stored in the
vault, writes the result to data/facts/provenance.json, and the panel prints
the numbers it finds there. What the extractors wrote is never rewritten: a
copied excerpt that differs from the record is counted and listed, not fixed.

Normalisation is deliberately thin, and the same on both sides: the Federal
Register wraps lines at 70 columns (so "head-to-barrel" is stored as "head-"
newline "to-barrel"), inserts "[[Page 12345]]" markers mid-sentence, and the
extractors escaped fractions with backslashes; letter case carries no meaning.
Anything else that differs is a deviation and is reported as one.

The four canonical threshold excerpts (AC 43.13-1B, hand-typed on 2026-08-30)
are checked the same way against the stated page of the stored PDF, whose text
layer breaks words at line ends with a soft hyphen and a space ("dis\u00ad tance");
that break is the one extra thing removed on the PDF side (since 2026-09-03).

Run: uv run python -m scheinman.provenance
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[2]
RAW_ADS = REPO / "data" / "raw" / "ads"
FACTS = REPO / "data" / "facts"
RULES = REPO / "data" / "rules" / "seed_rules.json"
AC_PDF = REPO / "data" / "raw" / "AC_43.13-1B_w-chg1.pdf"
OUTPUT = FACTS / "provenance.json"
AD_LOTS = ("lot3-ad", "lot4-ads", "lot6-ads", "lot7-ads")
# The first AD lot predates the per-document shape: one record, facts flat.
SINGLE_DOCUMENT_LOTS = {"lot3-ad": "E7-9396"}
ELISION = re.compile(r"\s*(?:\[\.\.\.\]|\.\.\.|…)\s*")
PAGE_MARKER = re.compile(r"\[\[page \d+\]\]", re.IGNORECASE)
SOFT_HYPHEN_BREAK = re.compile("\u00ad\\s*")
MIN_PIECE = 12


def flat(text: str) -> str:
    text = PAGE_MARKER.sub(" ", text.replace("\\", ""))
    text = re.sub(r"-\s+", "-", text)
    return re.sub(r"\s+", " ", text).strip().lower()


def pieces(excerpt: str) -> list[str]:
    return [p for p in (flat(piece) for piece in ELISION.split(excerpt)) if len(p) >= MIN_PIECE]


def missing_pieces(excerpt: str, source: str) -> list[str]:
    return [piece for piece in pieces(excerpt) if piece not in source]


def stored_record(doc_id: str) -> str:
    path = RAW_ADS / f"{doc_id}.txt"
    if not path.exists():
        raise FileNotFoundError(f"the vault has no {path.relative_to(REPO)} for {doc_id}")
    return flat(path.read_text(encoding="utf-8", errors="replace"))


def documents(lot: str) -> dict[str, list[dict[str, Any]]]:
    merged = json.loads((FACTS / lot / "merged.json").read_text(encoding="utf-8"))
    if "documents" in merged:
        return {doc_id: doc["facts"] for doc_id, doc in merged["documents"].items()}
    return {SINGLE_DOCUMENT_LOTS[lot]: merged["facts"]}


def check_facts() -> dict[str, Any]:
    """Every AD fact excerpt against its stored record: totals and the list of
    the ones not found contiguously (never rewritten, always listed)."""
    checked = 0
    deviations: list[dict[str, str]] = []
    for lot in AD_LOTS:
        for doc_id, facts in documents(lot).items():
            source = stored_record(doc_id)
            for fact in facts:
                checked += 1
                for piece in missing_pieces(fact["snippet"], source):
                    deviations.append(
                        {
                            "lot": lot,
                            "document": doc_id,
                            "field": fact["field_id"],
                            "piece": piece[:120],
                        }
                    )
    return {
        "checked": checked,
        "found": checked - len({(d["lot"], d["document"], d["field"]) for d in deviations}),
        "deviations": deviations,
    }


def check_rule_anchors() -> list[str]:
    """Rule event anchors are hand-typed and must be verbatim without exception;
    returns the failures (empty when every anchor is in its record)."""
    failures: list[str] = []
    for rule in json.loads(RULES.read_text(encoding="utf-8"))["rules"]:
        for anchor in rule.get("event_anchors", []):
            match = re.search(r"data/raw/ads/([A-Za-z0-9-]+)\.txt", anchor["locator"])
            if not match:
                failures.append(f"{rule['rule_id']}: event anchor names no stored text file")
                continue
            for piece in missing_pieces(anchor["excerpt"], stored_record(match.group(1))):
                failures.append(f"{rule['rule_id']} ({anchor['source'][:40]}): {piece[:100]!r}")
    return failures


def flat_pdf(text: str) -> str:
    """The PDF side of flat(): a soft hyphen plus the line break after it is
    a word broken for layout, not a hyphen in the record."""
    return flat(SOFT_HYPHEN_BREAK.sub("", text))


def pdf_page_text(page: int, path: Path = AC_PDF) -> str:
    from pypdf import PdfReader  # the PDF reader is needed by this check only

    return PdfReader(str(path)).pages[page - 1].extract_text() or ""


def check_threshold_excerpts(rules: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """Every canonical threshold excerpt against the stated page of the stored
    AC PDF: how many were checked and which are not verbatim there."""
    if rules is None:
        rules = json.loads(RULES.read_text(encoding="utf-8"))["rules"]
    pages: dict[int, str] = {}
    checked = 0
    failures: list[str] = []
    for rule in rules:
        anchor = rule["threshold_anchor"]
        if anchor["kind"] != "canonical_citation":
            continue
        checked += 1
        match = re.search(r"PDF page (\d+)", anchor["locator"])
        if not match:
            failures.append(f"{rule['rule_id']}: threshold locator names no PDF page")
            continue
        page = int(match.group(1))
        if page not in pages:
            pages[page] = flat_pdf(pdf_page_text(page))
        if flat(anchor["excerpt"]) not in pages[page]:
            failures.append(
                f"{rule['rule_id']}: threshold excerpt is not verbatim on PDF page {page}"
            )
    return {"checked": checked, "failures": failures}


def report() -> dict[str, Any]:
    facts = check_facts()
    return {
        "comment": (
            "Generated by `uv run python -m scheinman.provenance`; never edited by hand. "
            "Every AD fact excerpt was searched, contiguously, in the stored Federal Register "
            "text after collapsing line wraps, page markers, fraction escapes and case. A fact "
            "listed under deviations is one whose excerpt is not a contiguous quote of the "
            "record (a paraphrase, an "
            "unmarked elision, or text stitched across a table). The readers' output is never "
            "rewritten. Pieces shorter than 12 characters between elision marks are not searched "
            "(too short to be distinctive). The canonical threshold excerpts are checked "
            "verbatim on the stated page of the stored AC 43.13-1B PDF (soft-hyphen line "
            "breaks removed) and reported under threshold_excerpts."
        ),
        "facts_checked": facts["checked"],
        "facts_found_contiguous": facts["found"],
        "facts_deviating": len(
            {(d["lot"], d["document"], d["field"]) for d in facts["deviations"]}
        ),
        "deviations": facts["deviations"],
        "rule_anchor_failures": check_rule_anchors(),
        "threshold_excerpts": check_threshold_excerpts(),
    }


def main() -> int:
    result = report()
    OUTPUT.write_text(json.dumps(result, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    print(
        f"{result['facts_found_contiguous']} of {result['facts_checked']} AD fact excerpts found "
        f"contiguously in the stored record; {result['facts_deviating']} deviate (listed in "
        f"{OUTPUT.relative_to(REPO)}); rule anchor failures: "
        f"{len(result['rule_anchor_failures'])}; threshold excerpts not verbatim: "
        f"{len(result['threshold_excerpts']['failures'])} of "
        f"{result['threshold_excerpts']['checked']}"
    )
    bad = result["rule_anchor_failures"] or result["threshold_excerpts"]["failures"]
    return 1 if bad else 0


if __name__ == "__main__":  # pragma: no cover - thin CLI wrapper
    raise SystemExit(main())
