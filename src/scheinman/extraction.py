"""Double-blind extraction: two independent readers, code as the judge.

Two extractors answer the same fixed form without seeing each other. This
module compares them field by field: agreement becomes a fact carrying its
verbatim snippet; any divergence or absence becomes a flagged blank holding
both candidates for human adjudication. Nothing here guesses.
"""

from __future__ import annotations

import re

from pydantic import BaseModel, ConfigDict


class FormField(BaseModel):
    """One question of the fixed extraction form.

    kind "text": free verbatim answer. kind "vocab": the answer MUST be one value
    from `allowed`. kind "vocab_multi": one or more values from `allowed`, joined
    by ";". Closed vocabularies exist so category answers cannot drift in wording;
    an answer outside the list is rejected, never silently accepted (design
    learning from the stage-3 pilot). "None" is always an explicit vocabulary
    value; null means only "could not read it".
    """

    model_config = ConfigDict(frozen=True)

    field_id: str
    question: str
    expected_unit: str  # "text" for verbatim/prose answers
    kind: str = "text"
    allowed: tuple[str, ...] = ()


class ExtractedField(BaseModel):
    """One extractor's answer to one form field. value=None means: not found or unsure."""

    model_config = ConfigDict(frozen=True)

    field_id: str
    value: str | None
    snippet: str | None  # verbatim text backing the value; mandatory when value is set
    page: int | None


class AgreedFact(BaseModel):
    model_config = ConfigDict(frozen=True)

    field_id: str
    value: str
    unit: str
    snippet: str
    page: int
    agreement: str = "both extractors, blind, identical after normalization"


class FlaggedBlank(BaseModel):
    """Divergence or absence: the honest outcome. Candidates kept for adjudication."""

    model_config = ConfigDict(frozen=True)

    field_id: str
    reason: str
    candidate_a: str | None
    candidate_b: str | None


class MergeResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    facts: tuple[AgreedFact, ...]
    blanks: tuple[FlaggedBlank, ...]

    @property
    def divergence_rate(self) -> float:
        total = len(self.facts) + len(self.blanks)
        return len(self.blanks) / total if total else 0.0


def _tokens(value: str) -> frozenset[str]:
    return frozenset(t.strip().lower() for t in value.split(";") if t.strip())


def _vocab_violations(value: str, field: FormField) -> set[str]:
    allowed = {a.lower() for a in field.allowed}
    tokens = _tokens(value) if field.kind == "vocab_multi" else {value.strip().lower()}
    return {t for t in tokens if t not in allowed}


def normalize(value: str) -> str:
    """Comparison form: case, spacing and thousands separators must not split a match.

    Range spellings collapse to one form ("0.010 to 0.249" == "0.010-0.249");
    the words only match whole (audit 2026-08-30: "stock" once became "s-ck").
    Documented tradeoff: a designation "10-32" and a range "10 to 32" still
    normalize identically; the range collapse is the feature that pays for it.
    """
    v = value.strip().lower()
    # Only the thousands pattern (digit, comma, exactly three digits) collapses;
    # a European decimal comma like "1,5" must not become another number
    # (deep audit 2026-09-01) — kept distinct, it honestly disagrees instead.
    v = re.sub(r"(?<=\d),(?=\d{3}(?:\D|$))", "", v)
    v = re.sub(r"\s+", " ", v)
    v = re.sub(r"\s*[-–]\s*|\s+(?:to|through)\s+", "-", v)
    return v


def load_extractor_output(raw: dict[str, object]) -> list[ExtractedField]:
    """Parse one extractor's raw JSON. Numeric values become the printed string form."""
    fields_raw = raw.get("fields")
    if not isinstance(fields_raw, list):
        raise ValueError("extractor output must carry a 'fields' list")
    seen: set[str] = set()
    out: list[ExtractedField] = []
    for item in fields_raw:
        if not isinstance(item, dict):
            raise ValueError("each field must be an object")
        field_id = str(item["field_id"])
        if field_id in seen:
            raise ValueError(
                f"duplicate answer for field {field_id!r}: a reader contradicting "
                "itself is rejected, never silently last-one-wins"
            )
        seen.add(field_id)
        value = item.get("value")
        snippet = item.get("snippet")
        page = item.get("page")
        out.append(
            ExtractedField(
                field_id=field_id,
                value=None if value is None else str(value),
                snippet=None if snippet is None else str(snippet),
                page=None if page is None else int(str(page)),
            )
        )
    return out


def load_form(raw: dict[str, object]) -> list[FormField]:
    fields_raw = raw.get("fields")
    if not isinstance(fields_raw, list):
        raise ValueError("form must carry a 'fields' list")
    fields = [FormField.model_validate(item) for item in fields_raw]
    ids = [f.field_id for f in fields]
    if len(ids) != len(set(ids)):
        dupes = sorted({i for i in ids if ids.count(i) > 1})
        raise ValueError(f"form carries duplicate field ids {dupes}; the vocabulary is closed")
    return fields


def merge(form: list[FormField], a: list[ExtractedField], b: list[ExtractedField]) -> MergeResult:
    by_a = {f.field_id: f for f in a}
    by_b = {f.field_id: f for f in b}
    known = {f.field_id for f in form}
    strays = sorted((set(by_a) | set(by_b)) - known)
    if strays:
        # Deep audit 2026-09-01: an answer under an unknown field id used to
        # vanish while the real field was blamed as unanswered.
        raise ValueError(
            f"reader answered under field ids the form does not know: {strays}; "
            "a stray answer is a defect to surface, never to swallow"
        )
    facts: list[AgreedFact] = []
    blanks: list[FlaggedBlank] = []
    for field in form:
        fa = by_a.get(field.field_id)
        fb = by_b.get(field.field_id)
        va = fa.value if fa else None
        vb = fb.value if fb else None
        if va is None and vb is None:
            blanks.append(
                FlaggedBlank(
                    field_id=field.field_id,
                    reason="neither extractor found it",
                    candidate_a=None,
                    candidate_b=None,
                )
            )
            continue
        if va is None or vb is None:
            blanks.append(
                FlaggedBlank(
                    field_id=field.field_id,
                    reason="only one extractor answered",
                    candidate_a=va,
                    candidate_b=vb,
                )
            )
            continue
        if field.kind in ("vocab", "vocab_multi"):
            bad_a = _vocab_violations(va, field)
            bad_b = _vocab_violations(vb, field)
            if bad_a or bad_b:
                blanks.append(
                    FlaggedBlank(
                        field_id=field.field_id,
                        reason=f"answer outside the closed vocabulary: {sorted(bad_a | bad_b)}",
                        candidate_a=va,
                        candidate_b=vb,
                    )
                )
                continue
        if field.kind == "vocab_multi":
            if _tokens(va) != _tokens(vb):
                blanks.append(
                    FlaggedBlank(
                        field_id=field.field_id,
                        reason="extractors disagree",
                        candidate_a=va,
                        candidate_b=vb,
                    )
                )
                continue
        elif normalize(va) != normalize(vb):
            blanks.append(
                FlaggedBlank(
                    field_id=field.field_id,
                    reason="extractors disagree",
                    candidate_a=va,
                    candidate_b=vb,
                )
            )
            continue
        assert fa is not None and fb is not None
        # An absence answer has nothing to quote, so reader A's anchor alone
        # carries it; a substantive value needs the anchor from BOTH readers
        # (audit 2026-08-30: a fact could be minted with B unanchored).
        absence = normalize(va) in ("none", "none_stated")
        b_anchored = absence or (bool(fb.snippet) and fb.page is not None)
        if not fa.snippet or fa.page is None or not b_anchored:
            blanks.append(
                FlaggedBlank(
                    field_id=field.field_id,
                    reason="agreed value lacks a verbatim snippet or page; without the "
                    "anchor from both readers it is not a fact",
                    candidate_a=va,
                    candidate_b=vb,
                )
            )
            continue
        facts.append(
            AgreedFact(
                field_id=field.field_id,
                value=va,
                unit=field.expected_unit,
                snippet=fa.snippet,
                page=fa.page,
            )
        )
    return MergeResult(facts=tuple(facts), blanks=tuple(blanks))
