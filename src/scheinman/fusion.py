"""Fusion: real failure events give weight to rules.

Practice and standards provide the number; the official failure record provides
the severity weight. This module crosses double-agreed AD facts with the rule
base by (material series, feature, mechanism) and reports, per rule, the real
events that document failure in the same combination. Only agreed facts feed
fusion; flagged blanks never do.

One documented code rule, not extractor judgment: a fatigue_cracking mechanism
is cyclic-loading evidence, because fatigue is by definition damage from
repeated load cycles.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from scheinman.ad_extraction import series_from_alloy
from scheinman.extraction import MergeResult
from scheinman.schemas import FeatureType, Loading, Rule, Severity

_FEATURE_MAP: dict[FeatureType, set[str]] = {
    FeatureType.EDGE_DISTANCE: {"fastener_hole"},
    FeatureType.HOLE: {"fastener_hole"},
    FeatureType.THICKNESS: {"skin_panel", "web"},
    FeatureType.CORNER_FILLET: {"radius_or_fillet"},
}

_LOADING_MECHANISMS: dict[Loading, set[str]] = {
    Loading.CYCLIC: {"fatigue_cracking"},
    Loading.STATIC: set(),  # no AD mechanism class evidences purely static failure
    Loading.ANY: {
        "fatigue_cracking",
        "stress_corrosion_cracking",
        "fracture_or_crack_unspecified",
    },
}

# Which rule quantities an event's feature class actually evidences (audit
# 2026-08-30): cracking AT fastener holes documents the hole-position risk the
# edge-distance rules govern, but says nothing about pitch or the
# diameter-over-thickness ratio; a rule outside this map gets no support from
# the event, however well feature and mechanism match.
_EVIDENCED_QUANTITIES: dict[str, set[str]] = {
    "fastener_hole": {"edge_distance_over_diameter"},
    "skin_panel": {"thickness_mm"},
    "web": {"thickness_mm"},
    "radius_or_fillet": {"corner_fillet_radius_mm"},
}


class AdEvent(BaseModel):
    """The double-agreed skeleton of one AD, ready for matching."""

    model_config = ConfigDict(frozen=True)

    document_number: str
    alloy_as_stated: str | None
    series: str
    feature_class: str | None
    mechanism_class: str | None
    snippets: tuple[str, ...]


def event_from_merged(document_number: str, result: MergeResult) -> AdEvent:
    values = {f.field_id: f.value for f in result.facts}
    snippets = tuple(f.snippet for f in result.facts)
    alloy = values.get("alloy_as_stated")
    return AdEvent(
        document_number=document_number,
        alloy_as_stated=alloy,
        series=series_from_alloy(alloy) if alloy else "unknown",
        feature_class=values.get("feature_class"),
        mechanism_class=values.get("mechanism_class"),
        snippets=snippets,
    )


def supports(rule: Rule, event: AdEvent) -> bool:
    """True when the event documents real failure in the rule's combination."""
    if event.feature_class is None or event.mechanism_class is None:
        return False
    if event.feature_class not in _FEATURE_MAP.get(rule.feature_type, set()):
        return False
    if rule.quantity not in _EVIDENCED_QUANTITIES.get(event.feature_class, set()):
        return False
    if event.mechanism_class not in _LOADING_MECHANISMS[rule.applies_to_loading]:
        return False
    if "any" in rule.applies_to_material_series:
        return True
    return event.series in rule.applies_to_material_series


def fuse(rules: list[Rule], events: list[AdEvent]) -> dict[str, list[str]]:
    """Per rule id: the document numbers of real events supporting its combination."""
    return {
        rule.rule_id: [e.document_number for e in events if supports(rule, e)] for rule in rules
    }


def promotion_candidates(rules: list[Rule], events: list[AdEvent]) -> dict[str, list[str]]:
    """WARN rules eligible for BLOCK, with the events that qualify them.

    Promotion policy (rule base v2, documented here and nowhere else): a rule
    may rise to BLOCK only when it names explicit material series. A rule that
    claims "any" material makes an unbounded claim that no finite set of events
    can cover, so it stays WARN no matter how many events match it. For an
    explicit-series rule, a qualifying event must match the full combination
    AND state an alloy in one of the rule's series.
    """
    out: dict[str, list[str]] = {}
    for rule in rules:
        if rule.severity is not Severity.WARN:
            continue
        if "any" in rule.applies_to_material_series:
            continue
        qualifying = [
            e.document_number
            for e in events
            if supports(rule, e) and e.series in rule.applies_to_material_series
        ]
        if qualifying:
            out[rule.rule_id] = qualifying
    return out
