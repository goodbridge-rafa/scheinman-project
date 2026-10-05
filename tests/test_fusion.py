"""Fusion: only agreed facts, matched in code, give weight to rules."""

from scheinman.extraction import AgreedFact, MergeResult
from scheinman.fusion import AdEvent, event_from_merged, fuse, promotion_candidates, supports
from scheinman.rules import load_rules
from scheinman.schemas import Severity


def _fact(field_id: str, value: str) -> AgreedFact:
    return AgreedFact(field_id=field_id, value=value, unit="text", snippet="s", page=1)


def _event(series: str, feature: str, mechanism: str) -> AdEvent:
    return AdEvent(
        document_number="X-1",
        alloy_as_stated="7075-T6",
        series=series,
        feature_class=feature,
        mechanism_class=mechanism,
        snippets=("s",),
    )


def test_event_is_built_only_from_agreed_facts() -> None:
    merged = MergeResult(
        facts=(
            _fact("alloy_as_stated", "7075-T6"),
            _fact("feature_class", "fastener_hole"),
            _fact("mechanism_class", "fatigue_cracking"),
        ),
        blanks=(),
    )
    event = event_from_merged("E7-9396", merged)
    assert event.series == "7xxx"
    assert event.feature_class == "fastener_hole"


def test_block_rule_is_supported_by_matching_combination() -> None:
    rules = load_rules()
    block = next(r for r in rules if r.rule_id == "R-0001")
    assert supports(block, _event("7xxx", "fastener_hole", "fatigue_cracking"))
    assert not supports(block, _event("6xxx", "fastener_hole", "fatigue_cracking"))
    assert not supports(block, _event("7xxx", "weld_joint", "fatigue_cracking"))
    assert not supports(block, _event("7xxx", "fastener_hole", "corrosion"))


def test_fuse_maps_rule_ids_to_supporting_documents() -> None:
    rules = load_rules()
    events = [
        _event("7xxx", "fastener_hole", "fatigue_cracking"),
        _event("unknown", "skin_panel", "corrosion"),
    ]
    report = fuse(rules, events)
    assert report["R-0001"] == ["X-1"]


def test_event_supports_only_quantities_it_evidences() -> None:
    # Audit 2026-08-30: a fastener-hole fatigue event was counted as support
    # for the pitch and diameter-over-thickness rules, whose quantities it says
    # nothing about. Support now requires the rule's quantity to be evidenced
    # by the event's feature class.
    rules = load_rules()
    event = _event("7xxx", "fastener_hole", "fatigue_cracking")
    by_id = {r.rule_id: r for r in rules}
    assert supports(by_id["R-0001"], event)  # edge distance: evidenced
    assert supports(by_id["R-0002"], event)  # edge distance: evidenced
    assert not supports(by_id["R-0003"], event)  # pitch: not evidenced
    assert not supports(by_id["R-0004"], event)  # diameter/thickness: not evidenced


def test_thickness_rule_is_still_supported_by_skin_and_web_events() -> None:
    rules = load_rules()
    r5 = next(r for r in rules if r.rule_id == "R-0005")
    assert supports(r5, _event("unknown", "skin_panel", "fatigue_cracking"))
    assert supports(r5, _event("unknown", "web", "fracture_or_crack_unspecified"))


def test_any_material_rule_is_never_promoted_to_block() -> None:
    rules = load_rules()
    # Every WARN seed rule claims "any" material; a finite set of aluminum events
    # cannot cover an unbounded claim, so nothing qualifies for promotion.
    events = [_event("7xxx", "fastener_hole", "fatigue_cracking")] * 20
    assert promotion_candidates(rules, events) == {}


def test_explicit_series_warn_rule_qualifies_with_matching_event() -> None:
    rules = load_rules()
    r2 = next(r for r in rules if r.rule_id == "R-0002")
    narrowed = r2.model_copy(update={"applies_to_material_series": ("7xxx",)})
    assert narrowed.severity is Severity.WARN
    matching = _event("7xxx", "fastener_hole", "fatigue_cracking")
    off_series = _event("2xxx", "fastener_hole", "fatigue_cracking")
    assert promotion_candidates([narrowed], [off_series]) == {}
    assert promotion_candidates([narrowed], [off_series, matching]) == {"R-0002": ["X-1"]}
