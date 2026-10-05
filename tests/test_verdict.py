"""The verdict is arithmetic over measurements, with a written-down resolution
and units that must agree (audit 2026-09-02)."""

import pytest

from scheinman.rules import load_rules, unit_of
from scheinman.schemas import FeatureType, Loading, Measurement, UsageContext
from scheinman.verdict import RESOLUTION, below_minimum, evaluate

CTX = UsageContext(material_series="7xxx", loading=Loading.CYCLIC)


def _ratio(feature_id: str, quantity: str, value: float, unit: str = "ratio") -> Measurement:
    return Measurement(
        feature_id=feature_id,
        feature_type=FeatureType.HOLE,
        quantity=quantity,
        value=value,
        unit=unit,
        method="test",
    )


def test_a_value_on_the_minimum_is_on_the_minimum() -> None:
    # 6 mm over 2 mm is exactly 3.0; a kernel that hands back 2.9999999 must not
    # print "measured 3.000, required 3.000, violation".
    assert below_minimum(3.0, 3.0) is False
    assert below_minimum(3.0 - RESOLUTION / 2, 3.0) is False
    assert below_minimum(2.999, 3.0) is True
    assert below_minimum(1.33, 2.0) is True
    rules = load_rules()
    on_the_line = [_ratio("hole-1", "hole_diameter_over_thickness", 3.0 - 1e-9)]
    assert evaluate(CTX, on_the_line, rules) == []


def test_units_must_agree_or_the_comparison_is_refused() -> None:
    rules = load_rules()
    inches = [_ratio("hole-1", "edge_distance_over_diameter", 1.0, unit="in")]
    with pytest.raises(ValueError, match="different units"):
        evaluate(CTX, inches, rules)


def test_the_unit_follows_from_the_quantity_name() -> None:
    assert unit_of("thickness_mm") == "mm"
    assert unit_of("hole_diameter_mm") == "mm"
    assert unit_of("edge_distance_over_diameter") == "ratio"
    for rule in load_rules():
        assert rule.unit == unit_of(rule.quantity), rule.rule_id
