"""Load design rules from the versioned rule base.

Loading IS validation: every rule passes the canonical gate in schemas.Rule
at construction time, so an unanchored rule cannot even be read from disk.
"""

from __future__ import annotations

import json
from pathlib import Path

from scheinman.schemas import KNOWN_QUANTITIES, AnchorKind, Rule

SEED_RULES_PATH = Path(__file__).resolve().parents[2] / "data" / "rules" / "seed_rules.json"


def load_rules(path: Path = SEED_RULES_PATH) -> list[Rule]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    rules = [Rule.model_validate(item) for item in raw["rules"]]
    for rule in rules:
        if rule.quantity not in KNOWN_QUANTITIES:
            raise ValueError(
                f"{rule.rule_id}: quantity {rule.quantity!r} is not one the measurer "
                "emits; such a rule would be silently green forever"
            )
        # The unit follows from the quantity's name, the same convention the
        # measurer emits: `_mm` quantities are millimetres, everything else is a
        # dimensionless ratio. A rule written in inches is refused at load
        # (audit 2026-09-02).
        if rule.unit != unit_of(rule.quantity):
            raise ValueError(
                f"{rule.rule_id}: quantity {rule.quantity!r} is measured in "
                f"{unit_of(rule.quantity)!r} but the rule states {rule.unit!r}"
            )
    return rules


def publishable_rules(path: Path = SEED_RULES_PATH) -> list[Rule]:
    """The rules a visitor's part is judged by: every anchored rule except the
    test fixtures, which exist to exercise the skeleton and are not engineering
    facts. Until 2026-09-02 the fixture R-0005 reached every delivered report."""
    return [r for r in load_rules(path) if r.threshold_anchor.kind is not AnchorKind.TEST_FIXTURE]


def unit_of(quantity: str) -> str:
    """The unit the measurer emits for a quantity name."""
    return "mm" if quantity.endswith("_mm") else "ratio"
