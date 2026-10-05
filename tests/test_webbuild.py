"""Every page the site ships must be built, addressed, and honest about itself.

The site had two skins between 2026-09-10 and 2026-09-11; the owner chose the
section view and version 1 was removed, so these tests describe one site again.
What they hold on to is what each removal could have broken: a page that is
built but not routed (lesson 023), a page that lost the navigation (lesson 024),
a sentence that claims something nothing measures (lesson 026), and an address
that used to work and now leads nowhere.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from scheinman.webbuild import NAV, build_gate, build_site, gate_tokens

REPO = Path(__file__).resolve().parents[1]
SITEKEY = "0x0000000000000000000000"
SECTIONS = ("home", "inspect", "archive", "evidence")


def _values(css: str) -> dict[str, str]:
    return {name: value.strip() for name, value in re.findall(r"(--[a-z0-9-]+):([^;]+);", css)}


def _built(tmp_path: Path) -> dict[str, str]:
    """The whole site, built once, as {page name: html}."""
    written = build_site(tmp_path, sitekey=SITEKEY)
    return {p.stem: p.read_text(encoding="utf-8") for p in written if p.suffix == ".html"}


def test_a_stylesheet_that_drops_its_token_block_stops_the_build(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr("scheinman.layout.shell", lambda: "/* no tokens here */")
    with pytest.raises(RuntimeError, match="shell.css"):
        gate_tokens()


def test_building_without_the_anti_robot_key_is_refused(tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.delenv("TURNSTILE_SITEKEY", raising=False)
    with pytest.raises(RuntimeError, match="anti-robot"):
        build_site(tmp_path)


def test_the_site_ships_every_page(tmp_path: Path) -> None:
    pages = _built(tmp_path)
    assert "gate" in pages, "the door is a page like any other"
    for section in SECTIONS:
        assert section in pages, f"{section}.html is not built"
    assert "index" not in pages, "there is no page without a name in the address bar"
    assert not any(name.startswith("v2-") for name in pages), (
        "version 2 became the site on 2026-09-11; a v2- file means half a removal"
    )


def test_no_placeholder_reaches_a_published_page(tmp_path: Path) -> None:
    for name, page in _built(tmp_path).items():
        assert not re.search(r"\$[A-Z_]{3,}", page), f"{name}.html still has a placeholder"


def test_a_site_behind_a_door_stays_out_of_search_engines(tmp_path: Path) -> None:
    # Decision 2026-09-01: a site with a password is not a public site. The two
    # generated pages (the evidence page) never carried this line until
    # 2026-09-11, because they are dressed rather than written here.
    for name, page in _built(tmp_path).items():
        assert "noindex" in page, f"{name}.html would be indexable"


def test_the_anti_robot_key_reaches_the_counter_and_the_address_is_written(tmp_path: Path) -> None:
    counter = _built(tmp_path)["inspect"]
    assert SITEKEY in counter
    assert "scheinman.example.com/inspect" in counter.lower()


def test_the_overview_is_the_map_of_the_whole_product(tmp_path: Path) -> None:
    page = _built(tmp_path)["home"]
    for section in ("/inspect", "/archive", "/evidence"):
        assert f'href="{section}"' in page, section
    # The samples live on the counter, where the file is needed, not on the
    # overview (owner's review, 2026-09-04).
    assert "/samples/" not in page


def test_the_samples_are_the_real_parts_and_behave_as_promised(tmp_path: Path) -> None:
    from scheinman.job import JobStatus, run_job
    from scheinman.schemas import Loading, UsageContext
    from scheinman.webbuild import write_samples

    context = UsageContext(material_series="7xxx", loading=Loading.CYCLIC)
    written = {p.name: p for p in write_samples(tmp_path / "samples")}
    assert set(written) == {"bracket-sample.step", "cover-sample.step"}
    # The counter tells the visitor what each one will do. It must be true.
    a = run_job(written["bracket-sample.step"], context, tmp_path / "a", part_name="bracket-sample")
    b = run_job(written["cover-sample.step"], context, tmp_path / "b", part_name="cover-sample")
    assert a.status is JobStatus.CORRECTED, "sample A promises a correction"
    assert b.status is JobStatus.CLEAN, "sample B promises a clean pass"


def test_the_archive_says_it_is_the_owners(tmp_path: Path) -> None:
    page = _built(tmp_path)["archive"]
    assert "Owner only" in page


def test_the_counter_answers_the_three_questions_on_every_screen(tmp_path: Path) -> None:
    # Where am I, what can I do here, what happened after I did it
    # (.claude/rules/interface.md). Every state is drawn, none is a blank page.
    page = _built(tmp_path)["inspect"]
    for marker in (
        'id="view-counter"',
        'id="view-progress"',
        'id="view-result"',
        'id="form-error"',
        "PASSED",
        "CORRECTED",
        "REPORTED",
        "REFUSED",
    ):
        assert marker in page, marker


def test_the_door_shows_the_name_and_asks_for_one_thing() -> None:
    # A stranger at the door learns the project's name and nothing else: no
    # counts, no status, no hint of what is behind it.
    page = build_gate(address="scheinman.example.com")
    assert "noindex" in page
    assert page.count('<input type="password"') == 1
    assert "Sign in" in page
    for leak in ("INSPECT", "ARCHIVE", "EVIDENCE", "job", "Turnstile"):
        assert leak not in page, f"the door must not mention {leak}"
    assert not re.search(r"\$[A-Z_]{3,}", page)


def test_the_door_is_built_from_the_palette_of_the_site_behind_it() -> None:
    # The door is the first page anyone sees. It carried version 1's palette
    # until 2026-09-11; a door of one world in front of another is the kind of
    # seam a visitor reads as two products.
    from scheinman.layout import shell

    door = build_gate(address="x")
    ground = _values(gate_tokens())
    world = _values(shell())
    assert ground and "--void" in door
    for token in ("--void", "--surface", "--ink", "--line"):
        assert ground[token] == world[token], f"the door and the site disagree about {token}"


def test_every_built_page_names_the_commit_it_came_from(tmp_path: Path) -> None:
    # Audit 2026-09-02: what is live must be provably what is in the
    # repository. Every page carries the build stamp; build.json serves it.
    import json as _json

    written = build_site(tmp_path, sitekey=SITEKEY)
    assert (tmp_path / "build.json") in written
    stamp = _json.loads((tmp_path / "build.json").read_text(encoding="utf-8"))
    assert set(stamp) == {"commit", "built_at", "tree", "base_path"}
    for name, page in _built(tmp_path).items():
        assert f'<meta name="scheinman-build" content="{stamp["commit"]} ' in page, name


def test_the_site_asks_the_owner_for_nothing(tmp_path: Path) -> None:
    """The guided conference was a page of Portuguese asking the owner to judge
    46 facts by hand. He read it on 2026-09-20 and asked what it was doing on
    his site: the adjudication is the session's work, not his. The page, its
    generator and its address are gone, and no page may ask him to do a job.
    """
    for name, page in _built(tmp_path).items():
        assert "conference2" not in page, f"{name} still points at the retired conference"


def _logic() -> str:
    return (REPO / "web" / "src" / "logic.mjs").read_text(encoding="utf-8")


def _routes() -> dict[str, str]:
    """The addresses the router answers, read from the one place that owns them."""
    block = re.search(r"export const PAGES = \{(.*?)\};", _logic(), re.DOTALL)
    assert block, "web/src/logic.mjs no longer declares the page addresses"
    routes = dict(re.findall(r"'(/[a-z0-9/]*)':\s*'([a-z0-9-]+)'", block.group(1)))
    assert routes, "the address map is empty"
    return routes


def test_every_built_page_has_an_address_and_every_address_has_a_page(tmp_path: Path) -> None:
    """Lesson 023: /conference2 was built, linked and green in every test, and
    still answered 404, because the router carries its own list of addresses.
    The builder is what knows the pages, so the binding is asserted from here.
    """
    routes = _routes()
    built = set(_built(tmp_path))
    # gate.html is served by the door itself, never by an address of its own.
    for name in built - {"gate"}:
        assert name in routes.values(), f"{name}.html is built but no address serves it"
    for path, name in routes.items():
        assert name in built, f"{path} is routed to {name}.html, which the builder does not write"
    assert {path for path, _ in NAV} == set(routes), "the navigation and the router disagree"


def test_the_addresses_version_two_used_still_lead_somewhere() -> None:
    """Version 2 answered under /v2 for a day, and those links were shared. They
    are redirected rather than 404'd: a link that worked yesterday must not make
    a working product look broken. The walk itself is tested in JavaScript
    (web/test/logic.test.mjs); here we only hold the router to having it.
    """
    logic = _logic()
    assert "RETIRED_PREFIX = '/v2'" in logic, "the old addresses lost their forwarding"
    worker = (REPO / "web" / "src" / "worker.mjs").read_text(encoding="utf-8")
    assert "movedFrom(path, base)" in worker and "status: 301" in worker


def test_every_page_carries_the_navigation_and_a_way_out(tmp_path: Path) -> None:
    """Lesson 024: the bar was copied into three templates and the panel's
    injected version, so a page added on 2026-09-03 appeared in none of them and
    the owner could not find it. One owner, and every page wears it.
    """
    for name, page in _built(tmp_path).items():
        if name == "gate":
            continue
        for path, label in NAV:
            assert f'href="{path}"' in page, f"{name}.html has no link to {path}"
            assert label in page, f"{name}.html does not name {label}"
        assert 'id="lock"' in page, f"{name}.html has no way to close the session"


def test_no_page_still_offers_a_version_that_no_longer_exists(tmp_path: Path) -> None:
    """The switch between the two skins was a link on every page. A leftover one
    would send the owner to a redirect and back to where they already were.
    """
    for name, page in _built(tmp_path).items():
        assert 'href="/v2' not in page, f"{name}.html still links into /v2"
        for gone in ("V01", "V02", "drawing sheet"):
            assert gone not in page, f"{name}.html still names {gone}"


def test_the_counter_offers_the_sample_parts_and_says_only_what_is_true(tmp_path: Path) -> None:
    """Owner's review, 2026-09-04: the samples belong beside the upload, and the
    page must not claim a STEP flavour nothing checks or a time nobody measured.
    """
    page = _built(tmp_path)["inspect"]
    assert "/samples/bracket-sample.step" in page
    assert "/samples/cover-sample.step" in page
    for invented in ("1 TO 3 MINUTES", "CHECKED BY: OWNER"):
        assert invented not in page, f"the counter still claims {invented}"


def test_the_pages_say_the_site_is_private(tmp_path: Path) -> None:
    pages = _built(tmp_path)
    for name in ("home", "inspect", "archive"):
        assert "not announced" in pages[name].lower(), name
    assert "PASSWORD REQUIRED" not in pages["home"]


# --- The base path (shared-host mounting, 2026-09-15) ---------------------------------
# Central hosting mounts this app under a prefix on a site it shares with other
# pages. The builder writes every address with that prefix; the router answers
# there. The two normalise the value separately, in two languages, so a test
# compares them: a page built for one prefix and routed under another is a site
# where every link is dead and every page looks fine.

BASE = "/apps/scheinman"


def _js_normalize(value: str) -> str:
    """What web/src/logic.mjs makes of the same value."""
    import json as _json
    import subprocess

    script = (
        "import { normalizeBase } from './web/src/logic.mjs';"
        f"process.stdout.write(JSON.stringify(normalizeBase({_json.dumps(value)})));"
    )
    out = subprocess.run(
        ["node", "--input-type=module", "-e", script],
        cwd=REPO,
        capture_output=True,
        text=True,
        check=True,
    )
    answer = _json.loads(out.stdout)
    assert isinstance(answer, str)
    return answer


def test_both_languages_normalise_a_base_path_the_same_way() -> None:
    from scheinman.layout import normalize_base

    for value in ("", "/", "///", BASE, BASE + "/", "apps/scheinman", "  /a//b/  "):
        assert normalize_base(value) == _js_normalize(value), f"the two disagree about {value!r}"


def test_without_a_base_path_nothing_about_the_live_site_changes(tmp_path: Path) -> None:
    for name, page in _built(tmp_path).items():
        assert "$BASE" not in page, f"{name}.html shipped an unfilled base marker"
        for section in ("/inspect", "/archive", "/evidence"):
            assert f'href="{section}"' in page or name in ("gate",), name


def test_under_a_prefix_every_address_a_page_writes_carries_it(tmp_path: Path) -> None:
    written = build_site(tmp_path, sitekey=SITEKEY, base_path=BASE)
    pages = {p.stem: p.read_text(encoding="utf-8") for p in written if p.suffix == ".html"}
    for name, page in pages.items():
        assert "$BASE" not in page, f"{name}.html shipped an unfilled base marker"
        # Nothing may point at the root of a hostname this app only borrows.
        for stray in re.findall(r'(?:href|action)="(/[^"]*)"', page):
            if stray.startswith(("//", "http")):
                continue
            assert stray.startswith(BASE), f"{name}.html points at {stray}, outside the prefix"
        for stray in re.findall(r"fetch\('(/[^']*)'", page):
            assert stray.startswith(BASE), f"{name}.html fetches {stray}, outside the prefix"


def test_the_build_stamp_says_which_prefix_it_was_made_for(tmp_path: Path) -> None:
    import json as _json

    build_site(tmp_path, sitekey=SITEKEY, base_path=BASE)
    assert _json.loads((tmp_path / "build.json").read_text(encoding="utf-8"))["base_path"] == BASE
    root = tmp_path / "root"
    build_site(root, sitekey=SITEKEY)
    assert _json.loads((root / "build.json").read_text(encoding="utf-8"))["base_path"] == ""


def test_the_owner_key_is_never_written_down_on_a_shared_origin(tmp_path: Path) -> None:
    """Browser storage is scoped to the ORIGIN, never to the path: under a
    prefix, any script on that hostname could read an owner key kept here
    (shared-host mounting, 2026-09-15). The pages decide from the base they were built
    with, so the decision cannot drift from where the site actually runs.
    """
    shared = build_site(tmp_path / "shared", sitekey=SITEKEY, base_path=BASE)
    pages = {p.stem: p.read_text(encoding="utf-8") for p in shared if p.suffix == ".html"}
    for name in ("archive", "inspect"):
        # Built with a prefix: the guard reads as true, so the key is used for
        # the request and never written down.
        assert f"'{BASE}' !== ''" in pages[name], f"{name} no longer decides by origin"

    root = _built(tmp_path / "root")
    for name in ("archive", "inspect"):
        # On its own hostname the guard reads as false and nothing changes.
        assert "'' !== ''" in root[name], f"{name} stopped remembering the key on its own origin"
    assert "localStorage" in root["archive"]

    # And the page says which of the two it is. Under a prefix it used to claim
    # "this key is remembered in this browser only" while remembering nothing.
    assert "The operator key is never stored in this browser." in pages["archive"]
    assert "$('forget').hidden = true" in pages["archive"]


def test_no_page_shows_an_em_dash(tmp_path: Path) -> None:
    """Owner's order, 2026-09-20: no em dash anywhere on the site. He reads the
    character as a machine's handwriting, and this site's whole claim is that a
    person can check every sentence on it.
    """
    for name, page in _built(tmp_path).items():
        assert "—" not in page, f"{name} has an em dash"
        assert "&mdash;" not in page, f"{name} has an em dash"


def test_a_dressed_page_is_given_colour_values_and_never_its_own_name_back() -> None:
    """`--ink: var(--ink)` is a cycle: CSS throws the property away and every
    rule that used it renders with nothing. Four tokens were empty that way on
    the evidence page until 2026-09-20, which is why its hover box was drawn
    with no background and could not be read.
    """
    from scheinman.layout import PANEL_TOKEN_MAP, _token_bridge, shell_tokens

    bridge = _token_bridge(PANEL_TOKEN_MAP)
    assert "var(" not in bridge, "a token bridge that names a token can name itself"
    values = shell_tokens()
    assert values["ink"] == "#e8eef9", "the palette moved; the bridge reads the wrong file"
    for theirs, ours in PANEL_TOKEN_MAP.items():
        assert f"--{theirs}: {values[ours]};" in bridge
