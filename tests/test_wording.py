"""The words the site says have one owner, and it agrees with the machine.

Until 2026-09-10 these sentences lived inside the counter's template, and
`web/test/logic.test.mjs` read that file to prove the page offered exactly what
the counter accepts. A second skin made a second copy of every one of them the
obvious next step, so the words moved to `scheinman.wording` and the assertions
moved here, to the side that owns them. The second skin became the site on
2026-09-11; the owner of the words stayed.
"""

from __future__ import annotations

import re
from pathlib import Path

from scheinman import wording
from scheinman.job import JobStatus
from scheinman.schemas import MATERIAL_SERIES

REPO = Path(__file__).resolve().parents[1]
LOGIC = (REPO / "web" / "src" / "logic.mjs").read_text(encoding="utf-8")


def _js_list(name: str) -> list[str]:
    """A closed vocabulary as the counter's own rules declare it."""
    match = re.search(rf"export const {name} = \[(.*?)\];", LOGIC, re.DOTALL)
    assert match, f"web/src/logic.mjs no longer declares {name}"
    return sorted(re.findall(r"'([^']+)'", match.group(1)))


def test_every_alloy_the_page_offers_is_one_the_counter_accepts() -> None:
    offered = sorted(option["value"] for option in wording.series_options())
    assert offered == sorted(MATERIAL_SERIES), "the counter offers a series the engine refuses"
    assert offered == _js_list("MATERIAL_SERIES"), "the page and the doorman disagree on alloys"


def test_every_loading_the_page_offers_is_one_the_counter_accepts() -> None:
    offered = sorted(value for value, _, _ in wording.LOADINGS)
    assert offered == _js_list("LOADINGS")


def test_every_way_a_job_can_end_has_a_stamp_and_every_stamp_is_a_real_ending() -> None:
    """The four the engine produces plus `error`, which only the counter makes.
    A status with no stamp would reach a visitor as a blank verdict.
    """
    rank = re.search(r"export const RANK = \{([^}]*)\}", LOGIC)
    assert rank, "web/src/logic.mjs no longer declares the progress ladder"
    terminal = {
        name
        for name, value in re.findall(r"(\w+): (\d)", rank.group(1))
        if value == "2"  # a rung a job never leaves
    }
    stamped = set(wording.VERDICTS)
    assert stamped == terminal, "a job can end in a state no page has words for"
    assert {str(s) for s in JobStatus} < stamped, "the engine's own statuses are all stamped"


def test_every_stamp_says_how_the_page_should_feel_about_it() -> None:
    for status, words in wording.VERDICTS.items():
        assert words["severity"] in {"pass", "note", "fail"}, status
        assert words["stamp"] and words["line"], status


def test_a_series_without_words_stops_the_build(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    without = dict(wording.SERIES_EXAMPLES)
    without.pop("7xxx")
    monkeypatch.setattr(wording, "SERIES_EXAMPLES", without)
    try:
        wording.series_options()
    except RuntimeError as error:
        assert "7xxx" in str(error)
    else:
        raise AssertionError("a declarable series with no words for a visitor must stop the build")


def test_the_refusal_sentences_are_written_in_exactly_one_place() -> None:
    """The guard against the next copy: if a refusal is ever pasted back into a
    template, this fails on that copy.
    """
    sentence = wording.REFUSALS[0][1]
    hits = [
        path
        for path in (REPO / "web").rglob("*.html")
        if "public" not in path.parts and sentence in path.read_text(encoding="utf-8")
    ]
    assert hits == [], f"the refusal wording is copied into {[str(p) for p in hits]}"
    assert sentence in wording.as_js()


def test_the_counter_is_served_these_words_and_no_others() -> None:
    """The counter reads one script tag for what it says, and it is this one."""
    from scheinman.layout import build_counter
    from scheinman.webbuild import NAV

    page = build_counter("0x0000000000000000000000TEST", address="x", nav=NAV, preview=True)
    assert wording.as_js() in page
    assert wording.VERDICTS[JobStatus.REFUSED]["stamp"] in page


def test_every_quantity_the_measurer_makes_has_a_word_for_a_reader() -> None:
    """The overview names the six quantities rather than printing "6 quantities"
    and leaving the reader to guess (owner, 2026-09-20). The list is the closed
    vocabulary's, so a quantity added to the machine without a word for it fails
    here instead of reaching a page as a field name.
    """
    from scheinman.schemas import KNOWN_QUANTITIES

    assert set(wording.QUANTITY_WORDS) == set(KNOWN_QUANTITIES)
    assert set(wording.QUANTITY_ORDER) == set(KNOWN_QUANTITIES)
    for name, word in wording.QUANTITY_WORDS.items():
        assert "_" not in word, f"{name} is shown to a reader as a field name"


def test_the_site_says_which_record_it_reads_today() -> None:
    """The machine is not an aviation machine, and the pages that make a claim
    about the record say which record that is (owner, 2026-09-20). The sentence
    has one owner, so the two pages cannot drift apart.
    """
    from scheinman.layout import build_home
    from scheinman.webbuild import NAV

    assert "FAA" in wording.SCOPE_TODAY and "aviation" in wording.SCOPE_TODAY
    page = build_home(address="x", nav=NAV)
    assert wording.SCOPE_TODAY in page
