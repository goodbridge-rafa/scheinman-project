"""The demo fabrication packages in data/reports are generated, never
hand-run one-shots: regenerating them must reproduce the committed files, and
the committed corrected STEP must re-measure to the same clean values."""

from pathlib import Path

from scheinman.measure import measure_step_file
from scheinman.report import write_demo_packages

REPO = Path(__file__).resolve().parents[1]
REPORTS = REPO / "data" / "reports"


def test_committed_demo_packages_are_fresh(tmp_path: Path) -> None:
    written = write_demo_packages(tmp_path)
    fresh_names = sorted(p.name for p in written)
    committed_names = sorted(p.name for p in REPORTS.iterdir())
    assert fresh_names == committed_names, (
        "data/reports content set drifted: regenerate with "
        "`uv run python -m scheinman.report` in the same commit"
    )
    for name in fresh_names:
        if name.endswith(".md"):
            assert (tmp_path / name).read_text() == (REPORTS / name).read_text(), (
                f"{name} is stale: regenerate with `uv run python -m scheinman.report`"
            )
        else:
            # STEP headers carry timestamps, so bytes differ run to run; the
            # committed artifact is pinned by re-measurement instead.
            fresh = {
                (m.feature_id, m.quantity): round(m.value, 3)
                for m in measure_step_file(tmp_path / name)
            }
            committed = {
                (m.feature_id, m.quantity): round(m.value, 3)
                for m in measure_step_file(REPORTS / name)
            }
            assert fresh == committed, f"{name} no longer matches what the pipeline produces"
