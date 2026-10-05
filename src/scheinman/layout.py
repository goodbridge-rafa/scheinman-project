"""The site's pages: the product, cut open.

The four things the engine does to a part are four slabs of one object, drawn in
isometric projection, and the interface is that drawing three times: the stack
on the overview, the live layer while a job runs, and the shape of a finished
verdict. `web/shell.css` carries the frame and `web/world.css` the parts;
this module carries what a page computes rather than writes, which is the rail,
the plate and the drawing itself.

This was version 2 of two skins over one product between 2026-09-10 and
2026-09-11, when the owner chose it, version 1 was removed and these files took
the plain names back.

Nothing here decides what the site *says* about a verdict, a refusal or a
delivery: that has one owner, `scheinman.wording`. The addresses have one owner
as well, `PAGES` in `web/src/logic.mjs`, mirrored by `webbuild.NAV`.

Run through `scheinman.webbuild`; it is what writes the files.
"""

from __future__ import annotations

import html
import math
import re
from pathlib import Path

from scheinman import wording

# The site's menu as the builder passes it around: (address, label) per section.
Nav = tuple[tuple[str, str], ...]

WEB_DIR = Path(__file__).resolve().parents[2] / "web"
SHELL_CSS = WEB_DIR / "shell.css"
WORLD_CSS = WEB_DIR / "world.css"
HOME_TEMPLATE = WEB_DIR / "home_template.html"
COUNTER_TEMPLATE = WEB_DIR / "inspect_template.html"
ARCHIVE_TEMPLATE = WEB_DIR / "archive_template.html"

FONTS = (
    "https://fonts.googleapis.com/css2?"
    "family=Archivo:wdth,wght@100..125,500..700"
    "&family=Hanken+Grotesk:wght@400;500;600"
    "&family=Spline+Sans+Mono:wght@400;500"
    "&display=swap"
)

# What each section is for, said before anyone clicks it. The addresses come
# from webbuild.NAV, the same map the router serves; these are only the words.
SECTION_NOTES = {
    "/": "the whole machine, in one drawing",
    "/inspect": "send a part, get a measured verdict",
    "/archive": "every job ever run, newest first",
    "/evidence": "where the rules come from",
}

# What each slab of the section drawing holds. The four steps themselves have
# one owner (wording.STEPS); this adds only what the drawing needs.
SLAB_ETCH = {
    "measure": "plate",
    "judge": "limits",
    "correct": "shift",
    "prove": "again",
}


def normalize_base(value: str) -> str:
    """A base path in one shape: "" for the root, or "/a/b" with no trailing
    slash.

    The mirror of `normalizeBase` in `web/src/logic.mjs`, and a test compares the
    two against the same inputs: a page built for one prefix and routed under
    another is a site of dead links, and nothing else would catch it.
    """
    trimmed = (value or "").strip()
    if not trimmed or trimmed == "/":
        return ""
    with_slash = trimmed if trimmed.startswith("/") else f"/{trimmed}"
    clean = re.sub(r"/{2,}", "/", with_slash.rstrip("/"))
    return "" if clean == "/" else clean


def shell() -> str:
    """The frame: tokens, ground, rail, plate. Also what a dressed page wears."""
    return SHELL_CSS.read_text(encoding="utf-8")


def world() -> str:
    """Everything a page of the site's own needs: the frame and the parts."""
    return shell() + "\n" + WORLD_CSS.read_text(encoding="utf-8")


# A page generated elsewhere carries its own palette under its own names. Rather
# than a second copy of the colours, the dressing maps that page's token names
# onto this world's, so the two can never drift: change a value in shell.css and
# the dressed pages change with it.
PANEL_TOKEN_MAP = {
    "paper": "surface",
    "paper-2": "raised",
    "paper-3": "void",
    "ink": "ink",
    "ink-2": "ink-2",
    "muted": "muted",
    "hairline": "hairline",
    "frame": "hairline-2",
    "grid": "grid-line",
    "accent": "line",
    "accent-ink": "line",
    "accent-soft": "line-soft",
    "block": "stop",
    "block-soft": "stop-soft",
    "warn": "live",
    "warn-soft": "live-soft",
    "note": "pass",
    "note-soft": "pass-soft",
}


_TOKEN_LINE = re.compile(r"^\s*--([a-z0-9-]+):\s*(.+?);\s*(?:/\*.*)?$")


def shell_tokens() -> dict[str, str]:
    """Every token in `web/shell.css`, by name, with its value.

    One owner for the palette: a page generated elsewhere is dressed from these
    values, so a colour changed in that file changes every page that wears it.
    """
    match = re.search(r":root \{(.*?)\n\}", shell(), re.DOTALL)
    if match is None:
        raise RuntimeError("web/shell.css no longer opens with a :root block")
    found = {}
    for line in match.group(1).splitlines():
        hit = _TOKEN_LINE.match(line)
        if hit:
            found[hit.group(1)] = hit.group(2).strip()
    return found


def _token_bridge(mapping: dict[str, str], extra: str = "") -> str:
    """The other page's token names, given this world's values.

    Values, never names. `--ink: var(--ink)` looks like the obvious way to say
    "use ours", but a custom property that names itself is a cycle: CSS throws
    it away, and every rule that used it renders with nothing. Four tokens on
    the evidence page were empty that way until 2026-09-20, which is why its
    hover box was drawn with no background at all.
    """
    values = shell_tokens()
    missing = sorted({ours for ours in mapping.values() if ours not in values})
    if missing:
        raise RuntimeError(f"web/shell.css has no token named: {', '.join(missing)}")
    lines = "\n".join(f"  --{theirs}: {values[ours]};" for theirs, ours in mapping.items())
    return f':root, :root[data-theme="dark"] {{\n{lines}\n}}{extra}'


def _dress(
    page: str,
    *,
    tokens: dict[str, str],
    current: str,
    nav: Nav,
    base: str,
    address: str,
    here: str,
    right: str,
    name: str,
    fixes: str = "",
) -> str:
    """Put a page built elsewhere inside this site's frame.

    The shell goes in before that page's own stylesheet, so the page keeps every
    rule it has about its own content, and the token bridge goes in after it, so
    the colours are this world's. The page's markup is never touched: it is the
    evidence itself, and a second copy of it is exactly what this repository
    does not allow.

    These two pages are generated elsewhere, so they never carried the line that
    keeps a site with a door out of search engines (decision 2026-09-01); the
    other pages hold it in their own templates. It is added here, so no page of
    a private site is left indexable. The day the door comes off, this goes with
    the rest of them.
    """
    root = normalize_base(base)
    page = page.replace("$BASE", root)
    robots = '<meta name="robots" content="noindex, nofollow">'
    css = f'{robots}\n<link rel="stylesheet" href="{FONTS}">\n<style>\n{shell()}\n</style>'
    bridge = f"<style>\n{_token_bridge(tokens, fixes)}\n</style>"
    opening = (
        f'<div class="frame">{rail_html(current, nav, base)}<div class="column">'
        f"{topbar_html(address=address, here=here, right=right)}"
    )
    closing = f"{FOOT}</div></div>\n{LOCK_SCRIPT}".replace("$BASE", root)

    if "<head>" in page and "<body>" in page:
        page = page.replace('<html lang="en">', '<html lang="en" data-theme="dark">', 1)
        page = page.replace("<head>", f"<head>\n{css}", 1)
        page = page.replace("</head>", f"{bridge}\n</head>", 1)
        page = page.replace("<body>", f"<body>\n{opening}", 1)
        if "</body>" not in page:
            raise RuntimeError(f"the generated {name} has no closing body tag to wrap")
        return page.replace("</body>", f"{closing}\n</body>", 1)

    # A fragment, served as a whole page: its own <style> is the first one, so
    # ours goes before it and the bridge immediately after it.
    marker = '<meta charset="utf-8">'
    if marker not in page or "</style>" not in page:
        raise RuntimeError(f"the generated {name} is not the document this dressing expects")
    page = page.replace(marker, f"{marker}\n{css}", 1)
    after_ours = page.index(css) + len(css)
    theirs = page.index("</style>", after_ours) + len("</style>")
    return page[:theirs] + f"\n{bridge}\n{opening}" + page[theirs:] + f"\n{closing}\n"


# ---------------------------------------------------------------------------
# The section drawing
#
# Isometric projection is one matrix: a point (u, v) on a slab's own plane
# lands at (0.866(u-v), 0.5(u+v)) on screen. Handing that matrix to SVG means
# the etchings are drawn as plain rectangles and circles in plain coordinates
# and come out as the rhombi and ellipses the projection makes of them, instead
# of being hand-plotted (and hand-mistaken) point by point.
# ---------------------------------------------------------------------------

COS30 = math.cos(math.radians(30))
HALF = 78.0  # half a slab, on its own plane
THICK = 10.0  # how deep a slab is, on screen
# How far apart the slabs are pulled. A slab is 2*HALF tall on screen, so this
# leaves them overlapping by about a quarter: enough to read as one object cut
# open, not so much that a layer hides the one under it.
GAP = 116.0
ISO = f"matrix({COS30:.4f} 0.5 {-COS30:.4f} 0.5 0 0)"


def _corners() -> dict[str, tuple[float, float]]:
    """A slab's corners on screen: a square seen at 30 degrees is a rhombus."""
    wide = HALF * 2 * COS30
    tall = HALF
    return {
        "top": (0.0, -tall),
        "right": (wide, 0.0),
        "bottom": (0.0, tall),
        "left": (-wide, 0.0),
    }


def _walls() -> str:
    """The two visible sides of a slab: what gives it thickness."""
    c = _corners()
    left = (
        f"{c['left'][0]:.1f},{c['left'][1]:.1f} "
        f"{c['bottom'][0]:.1f},{c['bottom'][1]:.1f} "
        f"{c['bottom'][0]:.1f},{c['bottom'][1] + THICK:.1f} "
        f"{c['left'][0]:.1f},{c['left'][1] + THICK:.1f}"
    )
    right = (
        f"{c['right'][0]:.1f},{c['right'][1]:.1f} "
        f"{c['bottom'][0]:.1f},{c['bottom'][1]:.1f} "
        f"{c['bottom'][0]:.1f},{c['bottom'][1] + THICK:.1f} "
        f"{c['right'][0]:.1f},{c['right'][1] + THICK:.1f}"
    )
    return f'<polygon class="wall" points="{left}"/><polygon class="wall" points="{right}"/>'


def _face() -> str:
    c = _corners()
    points = " ".join(f"{x:.1f},{y:.1f}" for x, y in (c["top"], c["right"], c["bottom"], c["left"]))
    return f'<polygon class="face" points="{points}"/>'


def _etch(kind: str) -> str:
    """What is drawn on a slab's surface, in the slab's own flat coordinates.

    Every mark is the thing that layer actually does to a plate: the plate and
    its two holes, the limit each hole has to clear, the hole being moved, and
    the second measurement that proves the move.
    """
    v = 'vector-effect="non-scaling-stroke"'
    inner = ""
    if kind == "plate":
        inner = (
            f'<rect class="etch" {v} x="-58" y="-38" width="116" height="76"/>'
            f'<circle class="etch" {v} cx="-26" cy="0" r="13"/>'
            f'<circle class="etch" {v} cx="26" cy="0" r="13"/>'
            f'<path class="etch" {v} d="M-58 52 H-26 M-58 47 V57 M-26 47 V57"/>'
        )
    elif kind == "limits":
        inner = (
            f'<rect class="etch" {v} x="-58" y="-38" width="116" height="76"/>'
            f'<path class="etch" {v} d="M-40 -38 V38 M-14 -38 V38 M12 -38 V38 M38 -38 V38"/>'
            f'<circle class="core" {v} cx="-26" cy="0" r="13"/>'
        )
    elif kind == "shift":
        inner = (
            f'<rect class="etch" {v} x="-58" y="-38" width="116" height="76"/>'
            f'<circle class="etch" {v} cx="-40" cy="0" r="13" stroke-dasharray="4 4"/>'
            f'<circle class="core" {v} cx="-14" cy="0" r="13"/>'
            f'<path class="etch" {v} d="M-34 -22 H-20 M-24 -26 L-19 -22 L-24 -18"/>'
        )
    else:  # again
        inner = (
            f'<rect class="etch" {v} x="-58" y="-38" width="116" height="76"/>'
            f'<circle class="etch" {v} cx="-14" cy="0" r="13"/>'
            f'<circle class="etch" {v} cx="26" cy="0" r="13"/>'
            f'<path class="etch" {v} d="M-58 -52 H-14 M-58 -57 V-47 M-14 -57 V-47"/>'
        )
    return f'<g transform="{ISO}">{inner}</g>'


def stack_svg(active: str | None = None, *, animate: bool = True) -> str:
    """The four slabs, drawn as one object seen in section.

    Drawn bottom slab first, because in this projection the slab above covers
    the one below and SVG has no z-order but document order. `active` lights one
    layer, which is what the counter does with the step a job is on.
    """
    steps = list(wording.STEPS)
    c = _corners()
    width = c["right"][0]
    height = (len(steps) - 1) * GAP + HALF * 2 + THICK
    view = f"{-width - 26:.0f} {-HALF - 26:.0f} {width * 2 + 52:.0f} {height + 52:.0f}"
    layers = []
    for index in reversed(range(len(steps))):
        key, name, _ = steps[index]
        on = " is-on" if key == active else ""
        # Position lives on the outer group and motion on the inner one: a CSS
        # transform on the same element would replace the attribute that puts
        # the slab in the stack, and every slab would animate into a pile at
        # the origin.
        style = (
            f' style="animation-delay: {index * 70}ms"' if animate else ' style="animation: none"'
        )
        layers.append(
            f'<g class="layer{on}" data-step="{key}" transform="translate(0 {index * GAP:.0f})">'
            f'<g class="settle"{style}>'
            f"{_walls()}{_face()}{_etch(SLAB_ETCH[key])}"
            f"</g></g>"
        )
    label = "; ".join(f"{i}. {name}" for i, (_, name, _) in enumerate(steps, start=1))
    return (
        f'<svg class="slabs" viewBox="{view}" role="img" '
        f'aria-label="Four stacked slabs seen in isometric section, one per step the engine '
        f'takes: {label}. Each slab is etched with what that step does to a plate." '
        f'focusable="false">{"".join(layers)}</svg>'
    )


def layers_list(figures: dict[str, str]) -> str:
    """The drawing's legend: the same four layers as text, with a real number.

    Everything the drawing shows is written here as well, because a drawing is
    not readable by a screen reader, a keyboard or a printer.
    """
    e = html.escape
    items = []
    for index, (key, name, note) in enumerate(wording.STEPS, start=1):
        figure = figures.get(key, "")
        items.append(
            f'<li data-step="{key}">'
            f'<div class="row">'
            f'<span class="k">{index:02d}</span>'
            f"<div><h3>{e(name)}</h3><p>{e(note)}</p></div>"
            f'<span class="fig">{figure}</span>'
            f"</div></li>"
        )
    return "\n".join(items)


# ---------------------------------------------------------------------------
# The frame
# ---------------------------------------------------------------------------


def rail_html(current: str, nav: tuple[tuple[str, str], ...], base: str = "") -> str:
    """The rail every page wears: who this is and where you can go.

    `nav` and `current` are the canonical addresses, the ones the router knows.
    The base path is added here, on the way out, so the section notes stay keyed
    by the address itself and a prefix never reaches that lookup.
    """
    root = normalize_base(base)
    links = []
    for path, label in nav:
        here = ' aria-current="page"' if path == current else ""
        note = SECTION_NOTES[path]
        links.append(
            f'      <a href="{root + path if path != "/" else (root or "/")}"{here}>'
            f"{html.escape(label)}"
            f"<small>{html.escape(note)}</small></a>"
        )
    return (
        '<aside class="rail">\n'
        f'  <a class="mark" href="{root or "/"}"><b>Scheinman</b>'
        "<span>Section view</span></a>\n"
        '  <nav aria-label="Sections">\n' + "\n".join(links) + "\n  </nav>\n"
        '  <div class="bottom">\n'
        '    <button type="button" class="signout" id="lock">Sign out of this browser</button>\n'
        "  </div>\n"
        "</aside>"
    )


def topbar_html(*, address: str, here: str, right: str = "") -> str:
    """The plate at the top: what this page is, and where it lives."""
    tail = f'<span class="right">{right}</span>' if right else ""
    return (
        '<div class="topbar">'
        '<span class="flag">Private &middot; not announced</span>'
        f'<span class="here">{html.escape(address)}{html.escape(here)}</span>'
        f"{tail}</div>"
    )


FOOT = (
    '<footer class="foot">'
    "<span>Scheinman &middot; engineering knowledge, measured</span>"
    "<span>Section view</span>"
    "</footer>"
)

# The one script every page runs: closing the door on this browser.
LOCK_SCRIPT = (
    "<script>document.getElementById('lock').addEventListener('click',function(){"
    "fetch('$BASE/api/gate/lock',{method:'POST'}).then(function(){location.reload();},"
    "function(){location.reload();});});</script>"
)


# ---------------------------------------------------------------------------
# The pages
# ---------------------------------------------------------------------------


# What the overview says each layer amounts to. Only where a real number exists:
# a layer with nothing countable behind it says nothing rather than something
# round and empty.
def _figures() -> dict[str, str]:
    from scheinman.rules import load_rules
    from scheinman.schemas import KNOWN_QUANTITIES

    return {
        "measure": f"{len(KNOWN_QUANTITIES)} quantities",
        "judge": f"{len(load_rules())} rules",
        "correct": "",
        "prove": "0 violations left",
    }


def figures_note() -> str:
    """What those three numbers are, named rather than implied.

    The owner read "6 quantities / 5 rules / 0 violations left" beside the
    drawing and asked what each one was (2026-09-20). They are counted from
    this build, so the sentence is generated from the same sources instead of
    being typed under them and left to rot.
    """
    from scheinman.rules import load_rules
    from scheinman.schemas import KNOWN_QUANTITIES

    words = [wording.QUANTITY_WORDS[name] for name in wording.QUANTITY_ORDER]
    if set(wording.QUANTITY_ORDER) != set(KNOWN_QUANTITIES):
        raise RuntimeError("the quantities the site names are not the ones the measurer produces")
    rules = load_rules()
    listed = ", ".join(words[:-1]) + f" and {words[-1]}"
    return (
        f"The figures are this build, counted when the page was made. The "
        f"{len(KNOWN_QUANTITIES)} quantities are {listed}. The {len(rules)} rules are the ones "
        f"loaded today, each one quoting the record it came from. Zero violations left is the "
        f"bar a correction has to clear on the re-measurement before the machine calls it proven."
    )


def _shell(
    page: str, *, address: str, here: str, current: str, nav: Nav, right: str, base: str = ""
) -> str:
    page = page.replace("$FONTS", FONTS)
    page = page.replace("$WORLD", world())
    page = page.replace("$RAIL", rail_html(current, nav, base))
    page = page.replace("$TOPBAR", topbar_html(address=address, here=here, right=right))
    page = page.replace("$FIGNOTE", html.escape(figures_note()))
    page = page.replace("$SCOPE", html.escape(wording.SCOPE_TODAY))
    page = page.replace("$FOOT", FOOT)
    page = page.replace("$LOCK", LOCK_SCRIPT)
    return page.replace("$BASE", normalize_base(base))


def _finished(page: str, name: str) -> str:
    left = [line for line in page.splitlines() if re.search(r"\$[A-Z_]{3,}", line)]
    if left:
        raise RuntimeError(f"the {name} template still has unfilled placeholders: {left}")
    return page


def build_home(*, address: str, nav: Nav, base: str = "") -> str:
    """The overview: the thesis, the section drawing, what has run, and what the
    rules are made of.

    The counts come from `scheinman.panel.collect_values`, which computes them
    from the stored sources and refuses to answer at all if the adjudicated
    invention rate is not zero. That refusal stops this build, which is the
    behaviour we want: a page that claims measured honesty must not be published
    by a repository that cannot prove it.
    """
    from scheinman.panel import collect_values

    values = collect_values()
    page = HOME_TEMPLATE.read_text(encoding="utf-8")
    page = _shell(
        page,
        address=address,
        here="/",
        current="/",
        nav=nav,
        base=base,
        right="Overview",
    )
    page = page.replace("$STACK", stack_svg())
    page = page.replace("$LAYERS", layers_list(_figures()))
    for key in (
        "AD_COUNT",
        "HANDBOOK_PAGES",
        "FACTS_TOTAL",
        "EXCERPTS_FOUND",
        "EXCERPTS_CHECKED",
        "INVENTION_RATE",
        "GOLD_RIGHT",
        "GOLD_TOTAL",
    ):
        page = page.replace(f"${key}", values[key])
    return _finished(page, "overview")


def max_upload_mb() -> int:
    """The upload cap, read from the rule that enforces it.

    The counter's rules live in JavaScript because the counter runs there. A
    page that promised a different number would be a lie with a test-shaped
    hole in it, so the number is read, never typed.
    """
    source = (WEB_DIR / "src" / "logic.mjs").read_text(encoding="utf-8")
    match = re.search(r"MAX_UPLOAD_BYTES\s*=\s*(\d+)\s*\*\s*1024\s*\*\s*1024", source)
    if match is None:
        raise RuntimeError(
            "web/src/logic.mjs no longer states MAX_UPLOAD_BYTES as a number of megabytes; "
            "the page cannot promise a cap it cannot read"
        )
    return int(match.group(1))


def material_options_html(indent: str = " " * 22) -> str:
    """The alloy choices, with the series separated from its examples by
    a colon rather than a dash: same facts, its own voice."""
    rows = []
    for option in wording.series_options():
        here = " selected" if option["value"] == wording.DEFAULT_SERIES else ""
        rows.append(
            f'{indent}<option value="{option["value"]}"{here}>'
            f"{option['value']}: {html.escape(option['examples'])}</option>"
        )
    return "\n".join(rows)


def loading_choices_html(indent: str = " " * 22) -> str:
    """The two loading declarations, as the counter's two-line choices."""
    rows = []
    for value, label, note in wording.LOADINGS:
        pressed = "true" if value == wording.LOADINGS[0][0] else "false"
        rows.append(
            f'{indent}<button type="button" data-loading="{value}" aria-pressed="{pressed}">'
            f"{html.escape(label)}<small>{html.escape(note)}</small></button>"
        )
    return "\n".join(rows)


def progress_steps_html(indent: str = " " * 16) -> str:
    """The four steps as a running job reports them."""
    rows = []
    for index, (name, note) in enumerate(wording.RUN_STEPS):
        state = ' data-state="done"' if index == 0 else ' data-state="active"' if index == 1 else ""
        rows.append(
            f'{indent}<li{state}><i class="pip" aria-hidden="true"></i>'
            f"<div><b>{html.escape(name)}</b><span>{html.escape(note)}</span></div></li>"
        )
    return "\n".join(rows)


def build_counter(sitekey: str, *, address: str, nav: Nav, preview: bool, base: str = "") -> str:
    """The counter: the four states a submitted part can be in."""
    page = COUNTER_TEMPLATE.read_text(encoding="utf-8")
    page = _shell(
        page,
        address=address,
        here="/inspect",
        current="/inspect",
        nav=nav,
        base=base,
        right="Step in &middot; proof out",
    )
    page = page.replace("$WORDING", wording.as_js())
    page = page.replace("$MATERIAL_OPTIONS", material_options_html())
    page = page.replace("$LOADING_CHIPS", loading_choices_html())
    page = page.replace("$PROGRESS_STEPS", progress_steps_html())
    page = page.replace("$STACK_RUNNING", stack_svg(active=wording.STEPS[0][0], animate=False))
    page = page.replace("$STACK", stack_svg())
    page = page.replace("$LAYERS", layers_list(_figures()))
    page = page.replace("$TURNSTILE_SITEKEY", sitekey)
    page = page.replace("$MAX_MB", str(max_upload_mb()))
    page = page.replace("$DEFAULT_LOADING", wording.LOADINGS[0][0])
    page = page.replace(
        "$ROBOTS", '<meta name="robots" content="noindex, nofollow">' if preview else ""
    )
    return _finished(page, "counter")


def build_archive(*, address: str, nav: Nav, base: str = "") -> str:
    """The owner's archive: every job ever run, newest first."""
    page = ARCHIVE_TEMPLATE.read_text(encoding="utf-8")
    page = _shell(
        page,
        address=address,
        here="/archive",
        current="/archive",
        nav=nav,
        base=base,
        right="Owner only",
    )
    return _finished(page, "archive")


def dress_panel(panel: str, *, address: str, nav: Nav, base: str = "") -> str:
    """The evidence page: the generated panel, in the site's frame and colours.

    The panel is built from the data by `scheinman.panel` and is the same
    evidence in both versions. Rebuilding it here would be a second copy of
    every number on it, so it is dressed, not rewritten.
    """
    return _dress(
        panel,
        tokens=PANEL_TOKEN_MAP,
        current="/evidence",
        nav=nav,
        base=base,
        address=address,
        here="/evidence",
        right="The case",
        name="panel",
    )
