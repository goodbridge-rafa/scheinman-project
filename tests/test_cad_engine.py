"""Smoke test: the CAD engine builds real geometry and we can measure it.

This is the stage-0 proof that the riskiest dependency (the 3D kernel behind
build123d) installs and runs headless in this environment and in CI. The
assertion is a measurement, not an import: SCHEINMAN's verdicts are arithmetic
over measurements, so measuring is the thing worth proving on day one.
"""

from build123d import Box


def test_cad_engine_builds_and_measures_a_box() -> None:
    box = Box(10, 20, 30)
    assert abs(box.volume - 10 * 20 * 30) < 1e-6
