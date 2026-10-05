"""Build the public site's pages from their single sources.

This module orchestrates: it owns the door, the navigation, the build stamp and
the sample parts, and hands every section page to `layout`, which draws them.
The evidence page is the generated panel itself, dressed but never rewritten.

Run: uv run python -m scheinman.webbuild
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path

from scheinman import layout

REPO = Path(__file__).resolve().parents[2]
PANEL_PAGE = REPO / "panel" / "index.html"
GATE_TEMPLATE = REPO / "web" / "gate_template.html"
PUBLIC = REPO / "web" / "public"

# The door reads its palette from the site's own stylesheet, so the first page
# anyone sees cannot drift away from the site behind it. It carries nothing else
# of the shell: no rail, no plate, none of the components. A page that has to
# stand alone in front of strangers holds only what it uses.
_ROOT_BLOCK = re.compile(r":root \{(.*?)\n\}", re.DOTALL)


def gate_tokens() -> str:
    """The site's design tokens, read from the file that owns them."""
    match = _ROOT_BLOCK.search(layout.shell())
    if match is None:
        raise RuntimeError(
            "web/shell.css no longer opens with a :root block; the door builds its "
            "palette from it and would silently stop looking like the site behind it"
        )
    return match.group(1).strip("\n")


def build_gate(*, address: str, base: str = "") -> str:
    """The door: the wordmark, the word admin, one field. Nothing else, because
    anything else on this page would be information a stranger has not earned."""
    page = GATE_TEMPLATE.read_text(encoding="utf-8")
    page = page.replace("$TOKENS", f":root {{\n{gate_tokens()}\n}}")
    page = page.replace("$FONTS", layout.FONTS)
    page = page.replace("$SITE_ADDRESS", address.upper())
    page = page.replace("$BASE", layout.normalize_base(base))
    left = [line for line in page.splitlines() if re.search(r"\$[A-Z_]{3,}", line)]
    if left:
        raise RuntimeError(f"the gate template still has unfilled placeholders: {left}")
    return page


def write_samples(directory: Path) -> list[Path]:
    """The two parts on the dashboard, built by the same generator the tests use.

    They are real geometry, not decoration: sample A breaks the edge-distance
    rules and comes back corrected, sample B passes clean.
    """
    from scheinman.parts import export_part, stage1_parts

    by_name = {spec.name: spec for spec in stage1_parts()}
    directory.mkdir(parents=True, exist_ok=True)
    written = []
    for sample, source in (("bracket-sample", "plate-edge-close"), ("cover-sample", "plate-clean")):
        built = export_part(by_name[source], directory)
        target = directory / f"{sample}.step"
        target.write_bytes(built.read_bytes())
        built.unlink()
        written.append(target)
    return written


def build_site(
    directory: Path = PUBLIC,
    *,
    sitekey: str | None = None,
    address: str = "scheinman.example.com",
    preview: bool = True,
    base_path: str | None = None,
) -> list[Path]:
    """Write every page the site serves. Returns what it wrote.

    `base_path` is the prefix the site will answer under: "" (the default) means
    the root, which is where the live deployment lives. A build for central
    hosting passes the assigned prefix, and every address the pages emit carries
    it (shared-host mounting, 2026-09-15). The value is stamped into build.json so the
    Worker can refuse to serve a build made for a different prefix.
    """
    base = layout.normalize_base(
        base_path if base_path is not None else os.environ.get("SCHEINMAN_BASE_PATH", "")
    )
    key = sitekey if sitekey is not None else os.environ.get("TURNSTILE_SITEKEY", "")
    if not key:
        raise RuntimeError(
            "TURNSTILE_SITEKEY is not set; the counter would ship without its anti-robot "
            "check. Set it in the environment (Cloudflare publishes a test sitekey for "
            "local builds)."
        )
    directory.mkdir(parents=True, exist_ok=True)
    pages = {
        "home.html": layout.build_home(address=address, nav=NAV, base=base),
        "inspect.html": layout.build_counter(
            key, address=address, nav=NAV, preview=preview, base=base
        ),
        "archive.html": layout.build_archive(address=address, nav=NAV, base=base),
        # The door stands in front of all of them, so it is built once.
        "gate.html": build_gate(address=address, base=base),
    }
    if PANEL_PAGE.exists():
        # The evidence page is the generated panel, dressed as one page of this site
        # (audit 2026-09-02). Its content is not touched.
        panel = PANEL_PAGE.read_text(encoding="utf-8")
        pages["evidence.html"] = layout.dress_panel(panel, address=address, nav=NAV, base=base)
    stamp = build_stamp() | {"base_path": base}
    written = []
    for name, html in pages.items():
        target = directory / name
        target.write_text(stamped(html, stamp), encoding="utf-8")
        written.append(target)
    # What is live must be provably what is in the repository: every page
    # carries the commit it was built from, and the counter serves the same
    # stamp at /api/version (audit 2026-09-02).
    version = directory / "build.json"
    version.write_text(json.dumps(stamp, indent=2) + "\n", encoding="utf-8")
    written.append(version)
    written += write_samples(directory / "samples")
    return written


# The site's navigation. One owner: it used to be copied into three templates
# and the panel's injected bar, so a page added on 2026-09-03 appeared in none
# of them and the owner could not find it (lesson 024). The addresses are the
# ones web/src/logic.mjs routes; a test binds the two.
NAV = (
    ("/", "Overview"),
    ("/inspect", "Inspect"),
    ("/archive", "Archive"),
    ("/evidence", "Evidence"),
)


def build_stamp() -> dict[str, str]:
    """The commit and the moment this build was made, from the real tree."""
    import subprocess
    from datetime import UTC, datetime

    def git(*args: str) -> str:
        try:
            return subprocess.run(
                ["git", *args], cwd=REPO, capture_output=True, text=True, check=True
            ).stdout.strip()
        except (OSError, subprocess.CalledProcessError):
            return "unknown"

    dirty = git("status", "--porcelain") != ""
    return {
        "commit": git("rev-parse", "--short=12", "HEAD"),
        "built_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "tree": "dirty" if dirty else "clean",
    }


def stamped(html: str, stamp: dict[str, str]) -> str:
    """One meta line per page naming the build it came from."""
    meta = (
        f'<meta name="scheinman-build" content="{stamp["commit"]} {stamp["built_at"]} '
        f'{stamp["tree"]}">'
    )
    marker = '<meta charset="utf-8">'
    if marker not in html:
        raise RuntimeError("a page without a charset meta cannot be stamped")
    return html.replace(marker, marker + "\n" + meta, 1)


if __name__ == "__main__":  # pragma: no cover - thin CLI wrapper
    for path in build_site():
        print(path)
