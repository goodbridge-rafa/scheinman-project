"""The shared vocabularies stay one: these tests bind every consumer to the
owner registered in ecosystem/CONTRACTS.md, so a rename in one place breaks
the build instead of silently emptying a set intersection (lesson 004; audit
2026-08-30 finding 9)."""

import json
import re
from pathlib import Path

import pytest

from scheinman.fusion import _EVIDENCED_QUANTITIES, _FEATURE_MAP, _LOADING_MECHANISMS
from scheinman.rules import load_rules
from scheinman.schemas import KNOWN_QUANTITIES

REPO = Path(__file__).resolve().parents[1]


def _form_allowed(field_id: str) -> set[str]:
    form = json.loads((REPO / "prompts" / "ad_form_v2.json").read_text())
    field = next(f for f in form["fields"] if f["field_id"] == field_id)
    return set(field["allowed"])


def test_fusion_feature_classes_exist_in_the_form_vocabulary() -> None:
    allowed = _form_allowed("feature_class")
    used = set().union(*_FEATURE_MAP.values()) | set(_EVIDENCED_QUANTITIES)
    assert used <= allowed, f"fusion uses feature classes outside the form: {used - allowed}"


def test_fusion_mechanisms_exist_in_the_form_vocabulary() -> None:
    allowed = _form_allowed("mechanism_class")
    used = set().union(*_LOADING_MECHANISMS.values())
    assert used <= allowed, f"fusion uses mechanisms outside the form: {used - allowed}"


def test_evidenced_quantities_are_known_quantities() -> None:
    used = set().union(*_EVIDENCED_QUANTITIES.values())
    assert used <= KNOWN_QUANTITIES


def test_every_seed_rule_quantity_is_measurable() -> None:
    assert {r.quantity for r in load_rules()} <= KNOWN_QUANTITIES


def test_rule_with_unmeasurable_quantity_is_refused_at_load(tmp_path: Path) -> None:
    raw = json.loads((REPO / "data" / "rules" / "seed_rules.json").read_text())
    raw["rules"][0]["quantity"] = "edge_distance_over_diamter"  # the audited typo class
    bad = tmp_path / "rules.json"
    bad.write_text(json.dumps(raw), encoding="utf-8")
    with pytest.raises(ValueError, match="silently green"):
        load_rules(bad)


def test_job_status_vocabulary_matches_the_contract_page() -> None:
    # The counter draws one screen per status, so a fifth status added in code
    # would reach the public page with no screen behind it. The contract page
    # names them; this test makes drift break the build (registered 2026-09-01).
    from scheinman.job import JobStatus

    row = next(
        line
        for line in (REPO / "ecosystem" / "CONTRACTS.md").read_text(encoding="utf-8").splitlines()
        if line.startswith("| job status |")
    )
    listed = {token for token in re.findall(r"`([a-z_]+)`", row)}
    assert listed == {s.value for s in JobStatus}


def test_delivery_file_roles_match_the_contract_page() -> None:
    from scheinman.job import JobResult

    row = next(
        line
        for line in (REPO / "ecosystem" / "CONTRACTS.md").read_text(encoding="utf-8").splitlines()
        if line.startswith("| job delivery package |")
    )
    for role in ("submitted_step", "inspection_report", "correction_report", "corrected_step"):
        assert f"`{role}`" in row, f"{role} is written by the engine but absent from the contract"
    assert "files" in JobResult.model_fields


def test_measurer_emits_only_known_quantities(tmp_path: Path) -> None:
    from scheinman.measure import measure_step_file
    from scheinman.parts import export_part, stage1_parts

    ms = measure_step_file(export_part(stage1_parts()[0], tmp_path))
    assert {m.quantity for m in ms} <= KNOWN_QUANTITIES


def test_material_series_vocabulary_matches_the_counter_and_refuses_9xxx() -> None:
    # Cascade 2026-09-02: the counter offered "9xxx", a reserved series that
    # names no alloy, and the owner asked what it was. The engine owns the list
    # now; the worker's copy is pinned here so the two cannot drift again.
    from scheinman.schemas import MATERIAL_SERIES, Loading, UsageContext

    assert tuple(f"{n}xxx" for n in range(1, 9)) == MATERIAL_SERIES
    logic = (REPO / "web" / "src" / "logic.mjs").read_text(encoding="utf-8")
    line = next(ln for ln in logic.splitlines() if ln.startswith("export const MATERIAL_SERIES"))
    assert tuple(re.findall(r"'([1-9]xxx)'", line)) == MATERIAL_SERIES
    row = next(
        line
        for line in (REPO / "ecosystem" / "CONTRACTS.md").read_text(encoding="utf-8").splitlines()
        if line.startswith("| declarable alloy families |")
    )
    assert "`1xxx`" in row and "`8xxx`" in row
    with pytest.raises(ValueError, match="material_series must be one of"):
        UsageContext(material_series="9xxx", loading=Loading.CYCLIC)
    assert UsageContext(material_series="8xxx", loading=Loading.STATIC).material_series == "8xxx"


def test_a_rule_in_the_wrong_unit_is_refused_at_load(tmp_path: Path) -> None:
    # Audit 2026-09-02: a stage-2 rule written in inches would have
    # been judged against millimetres in silence.
    raw = json.loads((REPO / "data" / "rules" / "seed_rules.json").read_text())
    raw["rules"][0]["unit"] = "in"
    bad = tmp_path / "rules.json"
    bad.write_text(json.dumps(raw), encoding="utf-8")
    with pytest.raises(ValueError, match="measured in 'ratio' but the rule states 'in'"):
        load_rules(bad)
