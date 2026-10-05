"""The canonical gate is code: invalid claims must fail at construction."""

import pytest
from pydantic import ValidationError

from scheinman.schemas import (
    Anchor,
    AnchorKind,
    Confidence,
    FeatureType,
    Loading,
    Rule,
    Severity,
    Violation,
)


def _canonical() -> Anchor:
    return Anchor(
        kind=AnchorKind.CANONICAL_CITATION,
        source="FAA AC 43.13-1B CHG 1",
        locator="Chapter 4, PDF page 159",
        excerpt="the edge distance should not be less than 2 times the diameter of the rivet",
    )


def _rule(**overrides: object) -> Rule:
    base: dict[str, object] = {
        "rule_id": "T-1",
        "applies_to_material_series": ("any",),
        "applies_to_loading": Loading.ANY,
        "feature_type": FeatureType.EDGE_DISTANCE,
        "quantity": "edge_distance_over_diameter",
        "minimum": 2.0,
        "unit": "ratio",
        "risk": "test",
        "severity": Severity.WARN,
        "confidence": Confidence.HIGH,
        "threshold_anchor": _canonical(),
    }
    base.update(overrides)
    return Rule.model_validate(base)


def test_anchor_with_empty_excerpt_is_rejected() -> None:
    with pytest.raises(ValidationError):
        Anchor(kind=AnchorKind.CANONICAL_CITATION, source="x", locator="y", excerpt="   ")


def test_block_without_event_anchor_is_rejected() -> None:
    with pytest.raises(ValidationError):
        _rule(severity=Severity.BLOCK)


def test_block_with_low_confidence_is_rejected() -> None:
    event = Anchor(
        kind=AnchorKind.OFFICIAL_EVENT_EXCERPT,
        source="FAA AD E7-9396",
        locator="data/raw/AD-E7-9396.txt",
        excerpt="fatigue cracking was found in upper deck floor beams",
    )
    with pytest.raises(ValidationError):
        _rule(severity=Severity.BLOCK, event_anchors=(event,), confidence=Confidence.MEDIUM)
    assert _rule(severity=Severity.BLOCK, event_anchors=(event,)).severity is Severity.BLOCK


def test_warn_threshold_must_be_canonical() -> None:
    measurement_anchor = Anchor(
        kind=AnchorKind.SYSTEM_MEASUREMENT, source="engine", locator="x", excerpt="v = 1"
    )
    with pytest.raises(ValidationError):
        _rule(threshold_anchor=measurement_anchor)


def test_violation_requires_measurement_and_source_anchors() -> None:
    with pytest.raises(ValidationError):
        Violation(
            rule_id="T-1",
            feature_id="hole-1",
            severity=Severity.WARN,
            measured=1.0,
            required_minimum=2.0,
            unit="ratio",
            explanation="x",
            anchors=(_canonical(),),
        )


def test_block_event_anchor_must_be_an_official_event_excerpt() -> None:
    # Deep audit 2026-09-01: the gate counted event anchors without checking
    # their kind, so a fully synthetic BLOCK could validate.
    not_an_event = _canonical()
    with pytest.raises(ValidationError):
        _rule(severity=Severity.BLOCK, event_anchors=(not_an_event,))


def test_warn_and_block_thresholds_reject_test_fixtures() -> None:
    fixture = Anchor(kind=AnchorKind.TEST_FIXTURE, source="s", locator="l", excerpt="e")
    with pytest.raises(ValidationError):
        _rule(threshold_anchor=fixture)
    # NOTE severity may keep fixture thresholds (the never-publishable demo rule).
    assert _rule(severity=Severity.NOTE, threshold_anchor=fixture).severity is Severity.NOTE


def test_violation_source_anchor_must_be_a_source_kind() -> None:
    from scheinman.schemas import Violation

    measurement = Anchor(
        kind=AnchorKind.SYSTEM_MEASUREMENT, source="engine", locator="x", excerpt="v = 1"
    )
    with pytest.raises(ValidationError):
        Violation(
            rule_id="T-1",
            feature_id="hole-1",
            severity=Severity.WARN,
            measured=1.0,
            required_minimum=2.0,
            unit="ratio",
            explanation="x",
            anchors=(measurement, measurement),
        )


def test_context_vocabulary_is_closed() -> None:
    from scheinman.schemas import UsageContext

    with pytest.raises(ValidationError):
        UsageContext(material_series="7075-T6", loading=Loading.CYCLIC)
    with pytest.raises(ValidationError):
        UsageContext(material_series="any", loading=Loading.CYCLIC)
    with pytest.raises(ValidationError):
        UsageContext(material_series="7xxx", loading=Loading.ANY)
    assert UsageContext(material_series="7xxx", loading=Loading.CYCLIC).material_series == "7xxx"
