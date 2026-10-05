"""Data contracts for SCHEINMAN.

The canonical gate lives here as code, not prose: an engineering claim cannot
exist without an anchor, and BLOCK severity cannot exist without both a
canonical threshold anchor and a real-failure event anchor. Invalid objects
fail at construction time.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, model_validator


class AnchorKind(StrEnum):
    """The only three valid anchors (project principle: no anchor, no fact)."""

    # A published canonical source (standard, handbook, advisory circular), with locator.
    CANONICAL_CITATION = "canonical_citation"
    OFFICIAL_EVENT_EXCERPT = "official_event_excerpt"  # verbatim excerpt of an AD/recall
    SYSTEM_MEASUREMENT = "system_measurement"  # measurement logged by this system
    TEST_FIXTURE = "test_fixture"  # synthetic, tests only; never publishable


class Anchor(BaseModel):
    """Where a claim comes from. Every field of every claim carries one."""

    model_config = ConfigDict(frozen=True)

    kind: AnchorKind
    source: str  # e.g. "MIL-HDBK-5J (31 Jan 2003)" or "measurement log"
    locator: str  # page/section/table, document id, or log reference
    excerpt: str  # the verbatim text or measurement record backing the claim

    @model_validator(mode="after")
    def _no_empty_backing(self) -> Anchor:
        if not self.source.strip() or not self.locator.strip() or not self.excerpt.strip():
            raise ValueError("an anchor with an empty source, locator or excerpt is not an anchor")
        return self


class Severity(StrEnum):
    NOTE = "NOTE"  # recorded in the report, no action demanded
    WARN = "WARN"  # canonical threshold exists, no documented real failure
    BLOCK = "BLOCK"  # canonical threshold AND documented real failure, same combination


class Confidence(StrEnum):
    """Discrete levels only. Uncalibrated percentages are forbidden (project principle)."""

    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class FeatureType(StrEnum):
    HOLE = "hole"
    EDGE_DISTANCE = "edge_distance"
    THICKNESS = "thickness"
    CORNER_FILLET = "corner_fillet"


class Loading(StrEnum):
    CYCLIC = "cyclic"
    STATIC = "static"
    ANY = "any"


# The alloy families a part can be declared as: the Aluminum Association's
# wrought series 1xxx..8xxx. There is no 9xxx (the series is reserved and holds
# no alloy); the counter offered it until 2026-09-02 and the owner rightly asked
# what it was. One owner for the vocabulary, registered in ecosystem/CONTRACTS.md;
# web/src/logic.mjs carries a copy that tests/test_contracts_binding.py pins here.
MATERIAL_SERIES: tuple[str, ...] = tuple(f"{n}xxx" for n in range(1, 9))


class UsageContext(BaseModel):
    """Declared by whoever submits the part. A CAD file holds shape, never purpose.

    Closed vocabulary at the trust boundary (deep audit 2026-09-01): a context
    written the natural way ("7075-T6") used to silently match no rule and pass
    green, and loading "any" degenerated the applicability test and switched
    the only BLOCK rule off. Both now fail loudly at construction.
    """

    model_config = ConfigDict(frozen=True)

    material_series: str  # one of MATERIAL_SERIES (use series_from_alloy to derive)
    loading: Loading

    @model_validator(mode="after")
    def _closed_vocabulary(self) -> UsageContext:
        if self.material_series not in MATERIAL_SERIES:
            raise ValueError(
                f"material_series must be one of {MATERIAL_SERIES}, got "
                f"{self.material_series!r}; derive it with "
                "scheinman.ad_extraction.series_from_alloy, never free text"
            )
        if self.loading is Loading.ANY:
            raise ValueError(
                "a submitted context must declare cyclic or static loading; 'any' is "
                "rule-side vocabulary and would silently disable loading-specific rules"
            )
        return self


# The closed vocabulary of measurable quantities. Single owner (registered in
# ecosystem/CONTRACTS.md): the measurer emits only these, the rule loader
# rejects anything else — a typo in a rule's quantity used to stay silently
# green because no measurement ever matched it (audit 2026-08-30).
KNOWN_QUANTITIES = frozenset(
    {
        "thickness_mm",
        "hole_diameter_mm",
        "hole_diameter_over_thickness",
        "edge_distance_over_diameter",
        "hole_pitch_over_diameter",
        "corner_fillet_radius_mm",
    }
)


class Rule(BaseModel):
    """A machine-checkable design rule. The verdict it produces is arithmetic."""

    model_config = ConfigDict(frozen=True)

    rule_id: str
    applies_to_material_series: tuple[str, ...]
    applies_to_loading: Loading
    feature_type: FeatureType
    # The check: measured[quantity] must be >= threshold (in `unit`, or a ratio).
    quantity: str  # e.g. "edge_distance_over_diameter", "thickness_mm"
    minimum: float
    unit: str  # "ratio" or "mm"
    risk: str  # human sentence: what happens when violated
    # What the source rule is for and what this project applies it to; printed
    # beside every finding so a reader can judge the stretch (audit 2026-09-02).
    scope: str = ""
    severity: Severity
    confidence: Confidence
    threshold_anchor: Anchor
    # Real failure records backing the severity. Rule base v2: a rule can carry
    # several; BLOCK still requires at least one.
    event_anchors: tuple[Anchor, ...] = ()

    @model_validator(mode="after")
    def _canonical_gate(self) -> Rule:
        if self.severity is Severity.BLOCK:
            if not any(a.kind is AnchorKind.OFFICIAL_EVENT_EXCERPT for a in self.event_anchors):
                raise ValueError(
                    "BLOCK requires a documented real failure (an official event excerpt "
                    "anchor) on top of the canonical threshold anchor; without it the "
                    "maximum severity is WARN"
                )
            if self.confidence is not Confidence.HIGH:
                raise ValueError("BLOCK cannot be emitted from a low/medium-confidence match")
        if (
            self.severity in (Severity.BLOCK, Severity.WARN)
            and self.threshold_anchor.kind is not AnchorKind.CANONICAL_CITATION
        ):
            raise ValueError(
                "WARN/BLOCK thresholds must cite a canonical source; synthetic fixtures "
                "stay at NOTE, the never-publishable severity"
            )
        return self


class Measurement(BaseModel):
    """One measured fact about one feature. Anchor kind: system_measurement."""

    model_config = ConfigDict(frozen=True)

    feature_id: str  # stable id within the part, e.g. "hole-1"
    feature_type: FeatureType
    quantity: str
    value: float
    unit: str
    method: str  # how it was measured, so the number is auditable

    def as_anchor(self) -> Anchor:
        return Anchor(
            kind=AnchorKind.SYSTEM_MEASUREMENT,
            source="scheinman measurement engine",
            locator=f"{self.feature_id}/{self.quantity}",
            excerpt=f"{self.quantity} = {self.value:.3f} {self.unit} via {self.method}",
        )


class Violation(BaseModel):
    """A rule broken by a measurement. Pure arithmetic; never model opinion."""

    model_config = ConfigDict(frozen=True)

    rule_id: str
    feature_id: str
    severity: Severity
    measured: float
    required_minimum: float
    unit: str
    explanation: str
    anchors: tuple[Anchor, ...]

    @model_validator(mode="after")
    def _every_claim_is_anchored(self) -> Violation:
        kinds = {a.kind for a in self.anchors}
        if AnchorKind.SYSTEM_MEASUREMENT not in kinds:
            raise ValueError("a violation must carry the measurement anchor that proves it")
        source_kinds = {
            AnchorKind.CANONICAL_CITATION,
            AnchorKind.OFFICIAL_EVENT_EXCERPT,
            AnchorKind.TEST_FIXTURE,
        }
        if not (kinds & source_kinds):
            raise ValueError(
                "a violation must carry the rule's source anchor besides the measurement; "
                "two measurements do not make a source"
            )
        return self
