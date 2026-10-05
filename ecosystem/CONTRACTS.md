# Shared contracts

A value is **shared** when more than one part of the system depends on it being exactly the same:
a name, a format, a key, a unit, a closed vocabulary, a route, an identifier.

**This page is the single source of truth.** Nothing copies a value from here; everything points
here. If the same value is defined in two places, one of them is wrong by construction. Several rows
are bound to the code by tests (`tests/test_contracts_binding.py`, `web/test/logic.test.mjs`), so
drift between this page and the code breaks the build.

| Value | What it is | Definition (the truth) |
|---|---|---|
| AD extraction vocabulary | closed lists for `feature_class`, `mechanism_class`, `component_class`, `action_class` | `prompts/ad_form_v2.json` (the `allowed` field of each question) |
| measurable quantities | the quantity names the measurer emits and a rule may use | `KNOWN_QUANTITIES` in `src/scheinman/schemas.py` |
| job status | the closed vocabulary for how every submitted part ends: `clean`, `corrected`, `uncorrected`, `refused` | `JobStatus` in `src/scheinman/job.py` |
| job delivery package | what the engine writes and the counter reads: the `result.json` file and the file roles inside it (`submitted_step`, `inspection_report`, `correction_report`, `corrected_step`). Both reports are PDF; the markdown renderer in `scheinman.report` produces the demo packages in `data/reports/` | `JobResult` and `RESULT_FILENAME` in `src/scheinman/job.py` |
| counter states | the states only the counter produces, before and outside the engine: `queued` (received, waiting for the engine), `running` (the engine picked it up), `error` (the engine did not finish; nothing was measured). With the engine's four they form the `RANK` ladder | `RANK` in `web/src/logic.mjs` |
| site origin | where the counter lives; the engine calls back to it and the pages print it | `SITE_ORIGIN` in `web/wrangler.jsonc` |
| page routes | each page's path and the file that serves it: `/`, `/inspect`, `/archive`, `/evidence`, relative to the base prefix. Retired paths answer with a permanent redirect (`RETIRED_PREFIX`, `movedFrom`) | `PAGES` in `web/src/logic.mjs` |
| base prefix | where the whole site is mounted: `""` is the root of its own hostname, and a prefix such as `/apps/scheinman` mounts the same app on a shared site. Every address a page writes, every route the Worker answers, the gate cookie `Path` and the engine's callback address derive from it | `normalizeBase` in `web/src/logic.mjs`, mirrored by `normalize_base` in `src/scheinman/layout.py`; each deployment's value is `BASE_PATH` (Worker) and `SCHEINMAN_BASE_PATH`/`base_path` (build), stamped into `build.json` |
| gate session lifetime | two limits, whichever comes first: 15 minutes idle (`SESSION_HOURS`, sliding, renewed on every response) and 2 hours since the password (`SESSION_MAX_HOURS`, a ceiling renewal cannot push). The cookie is a session cookie, but browsers that restore sessions return it, so the guarantee is time, not closing the browser | `SESSION_HOURS` and `SESSION_MAX_HOURS` in `web/src/logic.mjs` |
| site menu | the links every page shows, with their labels | `NAV` in `src/scheinman/webbuild.py` |
| counter wording | what the pages say about a verdict, a refusal, a declarable alloy, a job step and a delivered file | `src/scheinman/wording.py` |
| declarable alloy families | the closed vocabulary of the material declaration: wrought aluminium series `1xxx` to `8xxx` (there is no `9xxx`: the series is reserved and names no alloy) | `MATERIAL_SERIES` in `src/scheinman/schemas.py` |

## When a value enters this page
The moment a **second** part starts depending on it. Not before (bureaucracy), never after (that is
the first conflict).
