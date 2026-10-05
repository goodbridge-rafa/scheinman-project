# Lessons

Every incident becomes a check. A lesson without a check repeats. Each entry says what happened,
why it got through, and the check that now prevents it (and where that check lives). Code comments
cite these numbers.

## 001 — 2026-08-29 — parallel writers duplicate records
Writers running in parallel created dozens of duplicate records: each checked for a duplicate before
the other had written.
**Check:** helper agents get read-only tools; every write happens in one place, one at a time.

## 002 — 2026-08-29 — "triggered" is not "delivered"
A scheduler reported success and the work never happened; the check looked at the scheduler, not at
the destination.
**Check:** health is measured at the destination, with positive confirmation from the other side.

## 003 — 2026-08-29 — the merge is not the end
A merge race left `main` on a different version than the one reviewed, and it was declared done
without looking.
**Check:** after every merge, verify the real effect on the target, not the tool's word.

## 004 — 2026-08-29 — duplicated information becomes conflicting information
The same fact written in two documents aged at different speeds until the two disagreed.
**Check:** a single source of truth in `ecosystem/CONTRACTS.md`; copies become pointers, and tests
bind the code to that page.

## 005 — 2026-08-30 — a label grep matches the word, not the field
A status filter matched a word anywhere in a title, so prose mentioning it reopened a closed item.
**Check:** label matches are anchored to the field position and run against the real file in the
same change.

## 006 — 2026-08-30 — a hand-typed batch order invented data
When the first extraction batch was dispatched, the file list was typed by hand instead of copied
from the generated spec: 5 of 6 document numbers were invented. The blind readers caught it at once
(nulls with proof of absence) and nothing entered the base.
**Check:** batch orders are generated from the spec (`build_batch_prompt` in
`src/scheinman/ad_extraction.py`), and a test forbids any document number outside the spec
(`tests/test_ad_extraction.py`).

## 007 — 2026-09-01 — reader commentary inside the "verbatim" field
In the handbook lots, readers wrote location notes in parentheses inside the snippet, and the whole
field was then treated as literal page text. Nothing validated snippets against the source page, and
the evidence panel claimed "verbatim enforced" on that basis.
**Check:** the handbook files declare a `snippet_convention`;
`tests/test_shipped_artifacts.py::test_manual_lot_annotated_snippets_carry_the_convention_marker`
requires the marker wherever there is an annotation, and the panel now states what the merge really
requires instead of "verbatim enforced".

## 008 — 2026-09-01 — a vocabulary crossed languages and its check stayed behind
The closed vocabulary of job states was born in the engine (Python) with a test binding it to the
contract page, but the counter (JavaScript) needs the same names in two places. No test looked at
that side; a renamed state would have reached a visitor as "NOT RUN", a lie about their part.
**Check:** `web/test/logic.test.mjs` reads the contract page and requires every listed state to have
a rung on the ladder and a stamp on the page; proved failing by renaming a state first.
**Rule:** when a shared value crosses into another language or system, its check crosses in the same
commit.

## 009 — 2026-09-01 — the gate protected the API and left the pages wide open
The site password went live, tests passed, and the API answered "this site is not open". The pages
still opened for anyone: Cloudflare serves static assets before the Worker runs, so the gate never saw
those requests. Every test was on the code side, and the code was right; the error was in which layer
answers first. Found minutes after publishing, by requesting a page from outside without a cookie.
**Check:** `run_worker_first: true` in `web/wrangler.jsonc`, with the reason next to it, and a live
check (request every page without a password and require the gate) in the deploy script.
**Rule:** a new guard is proved from outside, on the real target, with no credentials.

## 010 — 2026-09-01 — an exception list is a list waiting to be incomplete
The gate was written with a list of exempt routes for the engine. One route was missing, so the first
two real jobs died with 401. The test checked exactly the list that had been written, so it agreed
instead of contradicting.
**Structural fix:** the gate stopped looking at the path and started looking at the credential. The
engine key, the owner key or a valid ticket is inside, whatever the address. `needsGate` has one
exception, the gate itself, and the test walks every route requiring all of them to sit behind it.
**Rule:** authorisation by exception list is debt; authorisation by presented credential is the rule.

## 011 — 2026-09-01 — a real password written into a versioned test
A constant-time comparison test used the real site password as its example. Nothing complained,
because the rule "no stored value outside the secrets file" only existed in prose.
**Check:** `tools/no-secret-leaks.sh` searches the repository for every value of the local secrets
file and fails on any hit; it runs inside `./check.sh` and is silent where no secrets file exists.
Proved by planting a value first. (The password was rotated.)
**Rule:** test examples are invented, never copied from what is live.

## 012 — 2026-09-02 — the gate lied about the wait
The ten-attempt lock counts per UTC hour and releases on the hour, while the message said "wait one
hour". The gate now says how many attempts are left and the exact time it reopens, and the counter
lives in an object that serialises attempts, so ten parallel guesses are counted as ten.
**Check:** `web/test/logic.test.mjs` (messages and hour rollover) and `web/test/worker.test.mjs`
(a burst of 30, exactly 10 compared).

## 013 — 2026-09-02 — the measurer assumed the part was centred on the origin
`describe_plate` added half the plate size to the hole coordinates, which only holds for a solid
centred on the origin. A corner-origin export (common in CAD) described a hole at (25, 15) as
(75, 45): every distance matched, the fidelity gate passed, and the corrected part would have been a
different, mirrored part. Found by audit and proved by experiment before touching code.
**Check:** the frame is now the minimum of the file's bounding box, stored in the description and
the rebuild; `tests/test_measure_honesty.py` (`corner_origin_*`).

## 014 — 2026-09-02 — a test rule reached the delivered file
A fixture rule marked "never publishable" was loaded for every visitor part, appeared in the report
and changed the corrected geometry.
**Rule:** only canonical WARN and BLOCK rules move metal; fixtures never reach the report.
**Check:** `tests/test_job.py` (`never_shows_the_test_fixture_rule`) and `tests/test_correction.py`
(`fixture_note_is_recorded_not_enforced`).

## 015 — 2026-09-02 — whoever reports a failure must not depend on what failed
The engine step that reported "I broke" ran through the project's own toolchain; if that toolchain
failed, nobody reported and the page spun forever. It is now plain `curl`, runs on cancellation too,
and the counter has a 30-minute watchdog that declares a job dead on read.
**Check:** `tests/test_deliver.py` (the workflow step) and `web/test/worker.test.mjs` (watchdog and
late delivery).

## 016 — 2026-09-02 — "verbatim excerpt" was a sentence, not a measurement
The evidence page said "every fact with its verbatim excerpt" and no command checked it. Measured:
497 of 507 AD excerpts are contiguous in the stored record; 10 deviate (paraphrase, unmarked elision,
table text) and are listed. One hand-typed rule anchor had a full stop the record does not have; it
was corrected to the literal text.
**Check:** `tests/test_provenance.py` and `data/facts/provenance.json` (freshness-tested).

## 017 — 2026-09-02 — the live page did not say which commit it came from
Every built page now carries its commit and build time; `/api/version` serves them; `web/deploy.sh`
only publishes a clean `main` equal to the remote and proves from outside that the live commit is the
one built.
**Check:** `tests/test_webbuild.py` (stamp on every page) and `web/deploy.sh` (fails loudly on a
mismatch).

## 018 — 2026-09-03 — four hand-typed sentences went four days without machine verification
The four AC 43.13-1B excerpts that give the rules their numbers were typed by hand and marked "not yet
machine-checked" because the tooling did not read PDF. The stored PDF has a text layer.
**Check:** `tests/test_provenance.py` finds the four excerpts on the page their locator names and
reports a wrong one.

## 019 — 2026-09-03 — an hourly watch ate a third of the free CI minutes
Twenty-four runs a day, each billed as a full minute, is about 730 of the 2,000 free monthly minutes
of a private repository, the same pool the engine runs on. Scheduled automation has a cost, measured
before switching it on. The external watch now runs once a day at most.

## 020 — 2026-09-03 — the form had no rule for damage across several components
A machine adjudication of 46 AD facts found one value outside the form's own rule and one tie caused
by an ambiguous question. No invention: both were gaps in the instructions. A closed vocabulary
without a tie-break rule produces answers that are defensible and out of rule at the same time.
**Check:** `tests/test_conference_machine.py` (the record stays bound to the facts it judged, the 6
planted decoys must be caught, contested items stay listed and are never rewritten) and the two new,
dated rules in `prompts/ad_form_v2.json`.

## 021 — 2026-09-03 — the deploy proof waited for the wrong sentence
The propagation wait watched a gate message that had been live since the day before, so it broke on
the first loop and judged a site that had not switched versions yet: a deploy that did publish was
reported as unproved. It also spent wrong-password attempts against the proof's own gate.
**Rule:** a wait must observe exactly the thing that changes.
**Check:** `tests/test_deploy_script.py` (the wait polls `/api/version` against the built commit and
never touches `/api/gate`).

## 022 — 2026-09-03 — GitHub's scheduler is best effort, and the watch depended on it alone
Measured on real runs: with an hourly cron, the watch ran 4 times in 10.4 hours, never on the
scheduled minute, with a 10.7-hour gap. The fast alarm moved to Cloudflare's own cron, which dispatches
`alert.yml` so the e-mail goes out.
**Check:** `web/test/worker.test.mjs` (rings when a job dies or stalls, stays quiet when healthy, and
a refused ring is retried).

## 023 — 2026-09-03 — a built page with no route: 404 on a page that existed
A new page was generated, linked and tested green, and still answered 404 live: the Worker router
had a fixed list of pages. A test that proves the builder does not prove the router.
**Check:** the route map lives in `web/src/logic.mjs` and `tests/test_webbuild.py` requires every
built page to have a route and every route a page. The first version of that check read the built
output folder and broke in CI, where the folder does not exist: a guard must live on the side that
knows how to build, never on a generated file.

## 024 — 2026-09-03 — the menu was copied in four places
A new page got a route and a card, and still could not be found: the top menu existed in four copies,
none updated. A page that is not in the menu does not exist for the person using the site.
**Check:** one owner for the menu (`NAV` in `src/scheinman/webbuild.py`); `tests/test_webbuild.py`
requires the menu and the router to list the same pages, and every page to carry every link.

## 025 — 2026-09-04 — an invisible space locked the owner out
The gate compared input character by character, so a pasted trailing space, a newline or browser
autofill became a wrong password and spent one of the hour's ten attempts. Proved live. The gate now
trims the ends before comparing (which never widens what opens: the stored password has no surrounding
whitespace, and a test proves a wrong value is still refused).
**Check:** `web/test/worker.test.mjs`.

## 026 — 2026-09-04 — the page text had never been checked against the code
All the proof discipline lived in the engine and the report, none in what the page says. The site
promised "1 to 3 minutes" (never measured), "STEP AP203/AP214" (nothing verifies it), a "checked by"
signature that does not exist and an invented drawing number. Visible text is a claim and needs the
same proof as a number in the report.
**Check:** `tests/test_webbuild.py` (no claim without a measurement on the pages).

## 027 — 2026-09-10 — the screenshot tool lied about the phone width
A screenshot showed the page overflowing a phone screen. Before "fixing" the layout, the page was
measured inside the browser: the document was exactly the viewport width. The error was the
screenshot mode, which did not apply the requested viewport. The measurement also found a real
overflow the screenshot hid.
**Rule:** before fixing what an image shows, measure the same thing another way.

## 028 — 2026-09-10 — animating `transform` erased SVG positions
CSS animation on `transform` replaces a `transform` attribute entirely, so every layer of a stacked
drawing collapsed onto the same spot while animating.
**Rule:** in SVG, never animate through CSS the same property an attribute uses for positioning; put
position on an outer group and animation on an inner one.

## 029 — 2026-09-15 — browser storage is per origin, never per path
Preparing to mount the app under a path prefix on a shared host, the owner key was still written to
`localStorage`, which is isolated by origin: any script on any page of that host could read it.
**Check:** `tests/test_webbuild.py` (`the_owner_key_is_never_written_down_on_a_shared_origin`)
requires prefixed builds to decide by the prefix; the gate cookie got the app's `Path`, tested in
`web/test/worker.test.mjs`.
**Rule:** when the address changes, re-read everything the browser stores.

## 030 — 2026-09-15 — the gate read the raw path and would answer with the wrong page
Under a prefix, `closedDoor` chose between "page" and "API" from the raw `url.pathname`: no API route
would be recognised, and an API client without a ticket would receive the gate HTML with 200 instead
of a 401.
**Check:** `web/test/worker.test.mjs` (`with a base path the site answers under it, and the door still
stands in front`).
**Rule:** when a value is stripped at an edge, every function still receiving the raw value is a
suspect.

## 031 — 2026-09-20 — a colour that points to its own name is not a colour
The bridge between the evidence page's palette and the site's wrote one line per token, and for four
tokens the names matched: `--ink: var(--ink);` is a cycle, so CSS discards it and everything using it
renders with nothing. No test saw it, because tests read HTML and colour only exists in the browser.
**Check:** `tests/test_webbuild.py`
(`test_a_dressed_page_is_given_colour_values_and_never_its_own_name_back`), and the build fails if a
token the bridge needs no longer exists.
**Rule:** a token bridge writes values, never names. Colour is checked in the browser, not in files.

## 032 — 2026-09-20 — a session cookie is not the browser closing
The requirement was "closing the browser asks for the password again". A session cookie is correct
and not enough: browsers that continue where they left off restore session cookies. The server never
observes the browser closing, so the only honest lever is time: 15 minutes idle (sliding, renewed on
every response) and a 2-hour ceiling since the password that renewal carries and never pushes.
**Check:** `web/test/worker.test.mjs` proves both limits and that renewal never resets the ceiling.
**Rule:** never promise a guarantee that depends on a user's browser settings.
