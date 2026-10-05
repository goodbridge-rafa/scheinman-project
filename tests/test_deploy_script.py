"""The deploy proof must wait on the thing it is proving.

Lesson 021 (2026-09-03): the propagation wait watched the door's
"attempts left" sentence, which had shipped the day before, so it broke on the
first try and judged a site that had not switched versions yet. The result was
a false FAIL on a deploy that had in fact published.
"""

from __future__ import annotations

import re
from pathlib import Path

DEPLOY = Path(__file__).resolve().parents[1] / "web" / "deploy.sh"


def wait_loop() -> str:
    text = DEPLOY.read_text(encoding="utf-8")
    match = re.search(r"for _ in \$\(seq 1 \d+\); do(.*?)done", text, re.S)
    assert match, "deploy.sh no longer has a propagation wait loop"
    return match.group(1)


def test_the_wait_polls_the_version_route_and_compares_it_to_the_built_commit() -> None:
    loop = wait_loop()
    assert "/api/version" in loop
    assert '"$live" = "$commit"' in loop


def test_the_wait_never_spends_the_gate_attempts_it_later_measures() -> None:
    # Ten wrong passwords an hour lock the door; a wait that polls with a wrong
    # password could lock the proof out of the site it is proving.
    loop = wait_loop()
    assert "not-the-password" not in loop
    assert "/api/gate" not in loop
