// Run with: node --test web/test  (no test framework, no new dependency)
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { test } from 'node:test';
import { fileURLToPath } from 'node:url';

import {
  ALERT_EVERY_MS,
  DAILY_LIMIT,
  GATE_ATTEMPTS_PER_HOUR,
  GLOBAL_DAILY_LIMIT,
  LOADINGS,
  lockCookie,
  cookiePath,
  normalizeBase,
  withBase,
  withoutBase,
  MATERIAL_SERIES,
  MAX_UPLOAD_BYTES,
  MAX_UPLOAD_MB,
  PAGES,
  RANK,
  SESSION_ENDED,
  SESSION_HOURS,
  STALE_AFTER_MS,
  acceptsLateDelivery,
  canAdvance,
  countsAgainstDailyLimit,
  dayStamp,
  gateAttemptKey,
  globalRateKey,
  globalRefusal,
  healthSummary,
  hourStamp,
  humanCheckMode,
  indexEntry,
  indexKey,
  movedFrom,
  linkExpired,
  lockedMessage,
  lockoutLifts,
  needsGate,
  newJob,
  newJobId,
  newTicket,
  newestFirst,
  partNameFrom,
  publicUntil,
  publicView,
  rateRefusal,
  readCookie,
  secretMatches,
  shouldAlert,
  staleJob,
  ticketValid,
  uploadRefusal,
  visitorBucket,
  wrongPasswordMessage,
} from '../src/logic.mjs';

const stepBytes = (name = 'part') =>
  new TextEncoder().encode(`ISO-10303-21;\nHEADER;\nFILE_NAME('${name}');\nENDSEC;\n`);

const good = { filename: 'bracket.step', bytes: stepBytes(), materialSeries: '7xxx', loading: 'cyclic' };

test('a real STEP file with both declarations is accepted', () => {
  assert.equal(uploadRefusal(good), null);
});

test('a renamed file without a STEP header is refused on its bytes, not its name', () => {
  const zip = new TextEncoder().encode('PK this is a zip pretending to be a part');
  const refusal = uploadRefusal({ ...good, bytes: zip });
  assert.match(refusal, /STEP header/);
});

test('a file over the size cap is refused with the size named', () => {
  const big = { ...good, bytes: new Uint8Array(MAX_UPLOAD_BYTES + 1) };
  assert.match(uploadRefusal(big), /10 MB/);
});

test('an empty file is refused before anything else', () => {
  assert.match(uploadRefusal({ ...good, bytes: new Uint8Array(0) }), /empty/);
});

test('declarations outside the closed vocabulary are refused', () => {
  assert.match(uploadRefusal({ ...good, materialSeries: '7075-T6' }), /alloy series/);
  assert.match(uploadRefusal({ ...good, loading: 'any' }), /cyclically or statically/);
});

test('a filename cannot smuggle a path', () => {
  assert.equal(partNameFrom('../../etc/passwd.step'), null);
  assert.equal(partNameFrom('bracket.step'), 'bracket');
  assert.equal(partNameFrom('bracket.STP'), 'bracket');
  assert.equal(partNameFrom('drawing.pdf'), null);
});

test('job ids are long enough to be the capability itself', () => {
  const id = newJobId(new Uint8Array(16).fill(255));
  assert.equal(id.length, 32);
  assert.match(id, /^[0-9a-f]+$/);
});

test('the daily limit refuses only after the allowance is spent', () => {
  assert.equal(rateRefusal(DAILY_LIMIT - 1), null);
  assert.match(rateRefusal(DAILY_LIMIT), /resets at midnight/);
});

test('the day stamp is the UTC day the limit counts in', () => {
  assert.equal(dayStamp(Date.parse('2026-09-01T23:59:59Z')), '2026-09-01');
  assert.equal(dayStamp(Date.parse('2026-09-02T00:00:01Z')), '2026-09-02');
});

test('the public link closes after thirty days and the job outlives it', () => {
  const now = Date.parse('2026-09-01T12:00:00Z');
  const job = newJob({ id: 'a'.repeat(32), partName: 'bracket', materialSeries: '7xxx', loading: 'cyclic', now });
  assert.equal(job.public_until, publicUntil(now));
  assert.equal(linkExpired(job, now + 29 * 86400000), false);
  assert.equal(linkExpired(job, now + 31 * 86400000), true);
});

test('the visitor bucket keeps no address, only a daily fingerprint', async () => {
  const day = '2026-09-01';
  const a = await visitorBucket('203.0.113.7', day);
  const b = await visitorBucket('203.0.113.7', day);
  const c = await visitorBucket('203.0.113.8', day);
  const tomorrow = await visitorBucket('203.0.113.7', '2026-09-02');
  assert.equal(a, b);
  assert.notEqual(a, c);
  assert.notEqual(a, tomorrow);
  assert.equal(a.includes('203.0.113'), false);
});

test('the public view never leaks fields the visitor has no business seeing', () => {
  const job = {
    ...newJob({ id: 'b'.repeat(32), partName: 'bracket', materialSeries: '7xxx', loading: 'cyclic', now: 0 }),
    engine_run_id: 12345,
    callback_secret: 'never-show-this',
    result: { status: 'clean', files: { inspection_report: 'bracket-inspection.pdf' } },
  };
  const view = publicView(job);
  assert.equal('callback_secret' in view, false);
  assert.equal('engine_run_id' in view, false);
  assert.deepEqual(view.files, ['inspection_report']);
});

test('a late message can never demote a finished job', () => {
  assert.equal(canAdvance('queued', 'running'), true);
  assert.equal(canAdvance('running', 'corrected'), true);
  assert.equal(canAdvance('corrected', 'running'), false);
  assert.equal(canAdvance('corrected', 'queued'), false);
  assert.equal(canAdvance('refused', 'clean'), false);
  assert.equal(canAdvance('running', 'invented-status'), false);
});

/* The job's state lives in a Durable Object because KV served a finished job
   as "queued" for up to a minute in the first live run. */
test('the job state answers a read with the write that just happened', async () => {
  const { JobState } = await import('../src/job_state.mjs');
  const store = new Map();
  const state = {
    storage: {
      get: async (k) => store.get(k),
      put: async (k, v) => void store.set(k, v),
    },
  };
  const object = new JobState(state);

  const missing = await object.fetch(new Request('https://job/state'));
  assert.equal(missing.status, 404);

  const job = { id: 'a'.repeat(32), status: 'corrected', files: { corrected_step: 'p.step' } };
  const written = await object.fetch(new Request('https://job/state', { method: 'PUT', body: JSON.stringify(job) }));
  assert.equal(written.status, 200);

  const read = await object.fetch(new Request('https://job/state'));
  assert.deepEqual(await read.json(), job);
});

/* The owner's archive: nothing is deleted when a visitor's link closes. */
test('the archive index sorts by time and carries only what a list needs', () => {
  const job = {
    ...newJob({ id: 'c'.repeat(32), partName: 'bracket', materialSeries: '7xxx', loading: 'cyclic', now: Date.parse('2026-09-01T13:00:00Z') }),
    status: 'corrected',
    engine_run_id: 999,
    result: { violations: [{ rule_id: 'R-0001' }, { rule_id: 'R-0002' }], files: { corrected_step: 'x.step' } },
  };
  const entry = indexEntry(job);
  assert.equal(entry.findings, 2);
  assert.equal(entry.status, 'corrected');
  assert.equal('result' in entry, false, 'the index is a list, not a copy of every job');
  assert.equal('engine_run_id' in entry, false);

  const older = { ...job, id: 'd'.repeat(32), created_at: '2026-08-31T13:00:00Z' };
  assert.ok(indexKey(older) < indexKey(job), 'keys must sort oldest first so a listing can be reversed');
});

/* Health audit 2026-09-01 found this gap: the job statuses were known in three
   places (the engine's JobStatus, the counter's ladder, the page's stamps) and
   only the engine side was bound to the contract page. A renamed status would
   have reached a visitor as "NOT RUN", which is a lie about their part. */
test('every status in the contract has a rung on the ladder and a stamp on the page', async () => {
  const repo = new URL('../../', import.meta.url);
  const contracts = readFileSync(fileURLToPath(new URL('ecosystem/CONTRACTS.md', repo)), 'utf8');
  const page = readFileSync(fileURLToPath(new URL('web/inspect_template.html', repo)), 'utf8');
  const worker = readFileSync(fileURLToPath(new URL('web/src/logic.mjs', repo)), 'utf8');

  const row = contracts.split('\n').find((line) => line.startsWith('| job status |'));
  assert.ok(row, 'the contract page must still name the job-status vocabulary');
  const statuses = [...new Set(row.match(/`([a-z_]+)`/g).map((m) => m.slice(1, -1)))];
  assert.ok(statuses.length >= 4);

  const rank = worker.match(/const RANK = \{([^}]*)\}/)[1];
  for (const status of statuses) {
    assert.match(rank, new RegExp(`\\b${status}\\b`), `${status} has no rung on the counter's ladder`);
  }
  // The page reads its stamps from scheinman.wording; that every ending has one
  // is proved in tests/test_wording.py, on the side that owns the words.
  assert.match(page, /window\.SCHEINMAN_WORDS/, 'the page no longer reads the shared wording');
});

/* The door (owner's decision 2026-09-01): one password in front of everything,
   and what the browser keeps is a signed ticket, never the password. */
test('a ticket opens the door only while it is valid, unaltered and for this password', async () => {
  const now = Date.parse('2026-09-01T12:00:00Z');
  const ticket = await newTicket('Correct Horse 12%', now);

  assert.equal(await ticketValid(ticket, 'Correct Horse 12%', now + 60_000), true);
  assert.equal(await ticketValid(ticket, 'Correct Horse 12%', now + SESSION_HOURS * 3600_000 + 1), false,
    'an expired ticket is not a ticket');
  assert.equal(await ticketValid(ticket, 'another password', now), false,
    'changing the password must lock every browser out');

  const [expires, signature] = ticket.split('.');
  const later = String(Number(expires) + 99_999_999);
  assert.equal(await ticketValid(`${later}.${signature}`, 'Correct Horse 12%', now), false,
    'a longer expiry with the old signature is a forgery');
  assert.equal(await ticketValid(`${expires}.${'0'.repeat(signature.length)}`, 'Correct Horse 12%', now), false);
  assert.equal(await ticketValid('', 'Correct Horse 12%', now), false);
  assert.equal(await ticketValid(null, 'Correct Horse 12%', now), false);
});

test('the ticket never carries the password itself', async () => {
  const password = 'a-long-example-password';
  const ticket = await newTicket(password, Date.parse('2026-09-01T12:00:00Z'));
  assert.equal(ticket.includes(password), false);
});

test('the cookie is read by name, not by position', () => {
  const header = 'other=1; scheinman_gate=123.abc; another=2';
  assert.equal(readCookie(header, 'scheinman_gate'), '123.abc');
  assert.equal(readCookie(header, 'missing'), null);
  assert.equal(readCookie('', 'scheinman_gate'), null);
  assert.equal(readCookie(null, 'scheinman_gate'), null);
});

test('the door stands in front of every address except itself', () => {
  // Live run 33524550342 taught this: the first version exempted the engine's
  // routes by path and missed one, so the engine was locked out of its own
  // counter and every job died. Now the path is never the question; the key
  // the request carries is, and that check lives in the worker.
  const id = 'a'.repeat(32);
  for (const path of ['/', '/inspect', '/archive', '/evidence', '/api/jobs',
                      `/api/jobs/${id}`, `/api/jobs/${id}/files/corrected_step`,
                      `/api/jobs/${id}/callback`, `/api/jobs/${id}/part`,
                      '/api/archive', '/samples/bracket-sample.step']) {
    assert.equal(needsGate(path), true, path);
  }
  assert.equal(needsGate('/api/gate'), false, 'the door itself cannot be behind the door');
});

test('a wrong password is refused and a right one is not, in constant time', () => {
  // Never the live password: health audit 2026-09-01 caught the real one
  // written into this file, which is versioned. A test proves the comparison,
  // and any string proves it.
  const example = 'Example-Password-42%';
  assert.equal(secretMatches(example, example), true);
  assert.equal(secretMatches(example.toLowerCase(), example), false);
  assert.equal(secretMatches(example.slice(0, -1), example), false);
  assert.equal(secretMatches('', ''), false, 'an unset password never opens anything');
  assert.equal(secretMatches(null, 'x'), false);
});

test('the attempt counter buckets by hour, so a lockout lifts by itself', () => {
  assert.equal(hourStamp(Date.parse('2026-09-01T13:59:59Z')), '2026-09-01T13');
  assert.equal(hourStamp(Date.parse('2026-09-01T14:00:01Z')), '2026-09-01T14');
  assert.notEqual(gateAttemptKey('v', '2026-09-01T13'), gateAttemptKey('v', '2026-09-01T14'));
  assert.ok(GATE_ATTEMPTS_PER_HOUR >= 5 && GATE_ATTEMPTS_PER_HOUR <= 20);
});

/* 2026-09-02: the owner locked himself out and was told to "wait an hour"; the
   counter is keyed by the UTC hour, so the truth was the next :00. The door now
   says what is left and when it reopens, and never lies about the wait. */
test('the door tells the truth about attempts left and when the lock lifts', () => {
  const at = Date.parse('2026-09-02T14:51:30Z');
  assert.equal(lockoutLifts(at).toISOString(), '2026-09-02T15:00:00.000Z');
  assert.equal(lockoutLifts(Date.parse('2026-09-02T23:59:59Z')).toISOString(), '2026-09-03T00:00:00.000Z');
  assert.equal(lockedMessage(at), 'Too many attempts. The door reopens at 15:00 UTC.');
  assert.match(wrongPasswordMessage(1, at), /9 attempts left this hour/);
  assert.match(wrongPasswordMessage(GATE_ATTEMPTS_PER_HOUR - 1, at), /1 attempt left this hour/);
  assert.match(wrongPasswordMessage(GATE_ATTEMPTS_PER_HOUR, at), /No attempts left this hour; the door reopens at 15:00 UTC/);
});

test('a reserved alloy series is not something the counter offers or accepts', () => {
  assert.equal(MATERIAL_SERIES.includes('9xxx'), false);
  assert.match(uploadRefusal({ ...good, materialSeries: '9xxx' }), /alloy series/);
});

/* Health audit 2026-09-01: the alloy list lives in the worker's closed
   vocabulary AND in the counter page's dropdown. If they drift, the page
   offers a value the door refuses, and the visitor is told to declare
   something the form never let them pick. */
/* What the page offers used to be typed into the template, and these two tests
   read it there. Since 2026-09-10 both versions of the site are filled in from
   scheinman.wording, so the same two assertions live in tests/test_wording.py,
   where that module can be imported instead of pattern-matched. What is still
   this side's to prove is that the counter's own vocabularies are the closed
   lists the engine declares, which tests/test_contracts_binding.py pins. */
test('the vocabularies the doorman enforces are closed lists, not free text', () => {
  assert.equal(uploadRefusal({ ...good, materialSeries: '9xxx' }), 'Declare the alloy series of the material.');
  assert.equal(uploadRefusal({ ...good, loading: 'sometimes' }), 'Declare whether the part is cyclically or statically loaded.');
  assert.ok(MATERIAL_SERIES.length === 8 && LOADINGS.length === 2);
});

/* For one day the site had two skins and version 2 answered under /v2 (owner's
   decision 2026-09-10, chosen 2026-09-11). Those addresses were shared while
   both were up, so every one of them still leads to the page it promised. */
test('every address version 2 used still leads to the same page, and nothing else redirects', () => {
  for (const path of Object.keys(PAGES)) {
    const old = path === '/' ? '/v2' : `/v2${path}`;
    assert.equal(movedFrom(old), path, `${old} no longer forwards to ${path}`);
    assert.equal(movedFrom(path), null, `${path} is a live address and must not redirect`);
  }
  assert.equal(movedFrom('/v2/nowhere'), null, 'an address nobody served has nowhere to forward to');
  assert.equal(movedFrom('/v2suffix'), null, 'only /v2 and what was under it is a retired address');
  assert.equal(movedFrom('/nowhere'), null);
});

/* The guard for what the audit found: no test may carry a live secret. */
test('this test file carries no credential-shaped literal (the repository-wide guard is tools/no-secret-leaks.sh in ./check.sh)', () => {
  const here = readFileSync(fileURLToPath(import.meta.url), 'utf8');
  // The shapes the project's real credentials take. A literal of any of these
  // shapes in a versioned file is a leak, whatever it is called.
  for (const shape of [/github_pat_[A-Za-z0-9_]{20,}/, /cfut_[A-Za-z0-9]{20,}/, /0x4AAAAAA[A-Za-z0-9_-]{10,}/]) {
    assert.equal(shape.test(here), false, `a live credential shape appears here: ${shape}`);
  }
});

/* Audit 2026-09-02. Four rules the door and the archive now live by. */
test('a job the engine never came back for is declared dead at read time, and only then', () => {
  const born = Date.parse('2026-09-02T14:00:00Z');
  const job = newJob({ id: 'd'.repeat(32), partName: 'bracket', materialSeries: '7xxx', loading: 'cyclic', now: born });
  assert.equal(staleJob(job, born + STALE_AFTER_MS - 1), null, 'still within the window: leave it');
  const dead = staleJob(job, born + STALE_AFTER_MS);
  assert.equal(dead.status, 'error');
  assert.match(dead.reason, /did not report back/);
  assert.equal(dead.finished_at, new Date(born + STALE_AFTER_MS).toISOString());
  assert.equal(job.status, 'queued', 'the original record is not mutated');
  assert.equal(staleJob({ ...job, status: 'corrected' }, born + 10 * STALE_AFTER_MS), null, 'a finished job is never touched');
  assert.equal(canAdvance('running', 'error'), true, 'the watchdog only moves the ladder forward');
});

test('the archive shows the newest jobs first, whatever order the store handed them back', () => {
  const entries = ['2026-09-01T10:00:00Z', '2026-09-02T09:00:00Z', '2026-08-31T23:59:59Z'].map((created_at, i) => ({ id: String(i), created_at }));
  assert.deepEqual(newestFirst(entries, 10).map((e) => e.created_at), ['2026-09-02T09:00:00Z', '2026-09-01T10:00:00Z', '2026-08-31T23:59:59Z']);
  assert.deepEqual(newestFirst(entries, 2).map((e) => e.id), ['1', '0'], 'a cap keeps the NEWEST, never the oldest');
});

test('locking the door empties and expires the same cookie the door issued', () => {
  assert.match(lockCookie(), /^scheinman_gate=; /);
  assert.match(lockCookie(), /Max-Age=0/);
  assert.match(lockCookie(), /HttpOnly/);
  assert.match(lockCookie(), /Path=\/;/);
  assert.match(lockCookie('/a/b'), /Path=\/a\/b;/, 'locking must clear the cookie it set');
  assert.equal(needsGate('/api/gate/lock'), true, 'only someone inside can lock; a stranger meets the door');
  assert.match(SESSION_ENDED, /Reload the page/);
});

test('the daily cap is for strangers; the owner is not a stranger', () => {
  assert.equal(countsAgainstDailyLimit(false), true);
  assert.equal(countsAgainstDailyLimit(true), false);
});

/* Audit 2026-09-02: the counter's global ceiling, the human check's honesty
   and the health line the six-hourly watch reads. */
test('everyone together has a daily ceiling, and it is spoken plainly', () => {
  assert.equal(globalRefusal(0), null);
  assert.equal(globalRefusal(GLOBAL_DAILY_LIMIT - 1), null);
  assert.match(globalRefusal(GLOBAL_DAILY_LIMIT), /for everyone together/);
  assert.equal(globalRateKey('2026-09-02'), 'rate:global:2026-09-02');
});

test('the human check verifies when configured, skips only on an explicit local switch, and otherwise closes', () => {
  assert.equal(humanCheckMode('0x-secret', undefined), 'verify');
  assert.equal(humanCheckMode('', 'true'), 'skip');
  assert.equal(humanCheckMode(undefined, undefined), 'closed');
  assert.equal(humanCheckMode('', 'false'), 'closed');
});

test('the health line counts errors and stalls, names no part, and knows when it is healthy', () => {
  const now = Date.parse('2026-09-02T15:00:00Z');
  const entries = [
    { created_at: '2026-09-02T14:00:00Z', status: 'corrected', part_name: 'secret-part' },
    { created_at: '2026-09-02T13:00:00Z', status: 'error' },
    { created_at: '2026-09-02T14:20:00Z', status: 'running' },
    { created_at: '2026-08-30T10:00:00Z', status: 'error' },
  ];
  const health = healthSummary(entries, now);
  assert.deepEqual(health, { jobs_24h: 3, errors_24h: 1, stalled: 1, last_job_at: '2026-09-02T14:20:00Z', healthy: false });
  assert.equal(JSON.stringify(health).includes('secret-part'), false);
  assert.equal(healthSummary([], now).healthy, true);
});

/* Audit 2026-09-02: three more bindings. */
test('a delivery that arrives after the watchdog gave up replaces the watchdog verdict, and only that', () => {
  const dead = { status: 'error', watchdog: true };
  assert.equal(acceptsLateDelivery(dead, 'corrected'), true);
  assert.equal(acceptsLateDelivery(dead, 'refused'), true);
  assert.equal(acceptsLateDelivery(dead, 'error'), false, 'a second error changes nothing');
  assert.equal(acceptsLateDelivery(dead, 'running'), false, 'the ladder never walks backwards');
  assert.equal(acceptsLateDelivery({ status: 'error' }, 'corrected'), false, 'an engine error is final');
  assert.equal(acceptsLateDelivery({ status: 'corrected', watchdog: true }, 'clean'), false);
});

test('the upload cap the page promises is the cap the counter enforces', () => {
  const page = readFileSync(
    fileURLToPath(new URL('web/inspect_template.html', new URL('../../', import.meta.url))),
    'utf8',
  );
  // The template writes the number through a placeholder the builder fills
  // from this same rule (layout.max_upload_mb), so the promise cannot drift.
  assert.match(page, /up to \$MAX_MB MB/);
  assert.ok(MAX_UPLOAD_MB > 0);
  assert.match(uploadRefusal({ ...good, bytes: new Uint8Array(MAX_UPLOAD_BYTES + 1) }), new RegExp(`up to ${MAX_UPLOAD_MB} MB`));
});

test('every status the counter or the page knows is written in the contract, and the other way round', () => {
  const contracts = readFileSync(
    fileURLToPath(new URL('ecosystem/CONTRACTS.md', new URL('../../', import.meta.url))),
    'utf8',
  );
  const rows = contracts.split('\n').filter((l) => l.startsWith('| job status |') || l.startsWith('| counter states |'));
  assert.equal(rows.length, 2, 'both rows exist');
  const written = new Set(rows.join(' ').match(/`([a-z_]+)`/g).map((t) => t.replace(/`/g, '')));
  assert.deepEqual(new Set(Object.keys(RANK)), written, 'the ladder and the contract name the same statuses');
  // That every terminal rung has a stamp, and no stamp exists for a state a job
  // never ends in, is proved in tests/test_wording.py against this same ladder.
  const terminal = new Set(Object.keys(RANK).filter((k) => RANK[k] === 2));
  assert.equal(terminal.size, 5, 'four endings from the engine plus the counter\'s own error');
});

test('a ticket signed with the Worker secret is worthless without it, and the password still kills it', async () => {
  const now = Date.parse('2026-09-02T12:00:00Z');
  const ticket = await newTicket('Correct Horse 12%', now, crypto.subtle, SESSION_HOURS, 'pepper-A');
  assert.equal(await ticketValid(ticket, 'Correct Horse 12%', now + 1000, crypto.subtle, 'pepper-A'), true);
  assert.equal(await ticketValid(ticket, 'Correct Horse 12%', now + 1000, crypto.subtle, 'pepper-B'), false, 'another secret, another site');
  assert.equal(await ticketValid(ticket, 'Correct Horse 12%', now + 1000, crypto.subtle, ''), false, 'no secret is not the same as the secret');
  assert.equal(await ticketValid(ticket, 'rotated', now + 1000, crypto.subtle, 'pepper-A'), false, 'rotating the password still ends every session');
});

test('the alarm rings only while unhealthy, and at most once per window', () => {
  const now = Date.parse('2026-09-03T22:00:00Z');
  const sick = { healthy: false, errors_24h: 2, stalled: 1 };
  assert.equal(shouldAlert({ healthy: true, errors_24h: 0, stalled: 0 }, null, now).ring, false);
  const first = shouldAlert(sick, null, now);
  assert.equal(first.ring, true);
  assert.match(first.reason, /^SCHEINMAN: 2 job\(s\) died in the last 24 h; 1 job\(s\) stalled/);
  assert.equal(shouldAlert(sick, '2026-09-03T21:00:00Z', now).ring, false, 'rang an hour ago');
  assert.equal(shouldAlert(sick, '2026-09-03T15:00:00Z', now).ring, true, 'rang seven hours ago');
  assert.equal(ALERT_EVERY_MS, 6 * 60 * 60 * 1000);
});

/* --- The base path (shared-host mounting, 2026-09-15) -------------------------------
   Central hosting mounts this app under a prefix on a site it shares with
   other pages. Every address it emits and answers has to carry that prefix,
   and the default of "" has to leave the live deployment exactly as it was. */

test('a base path is normalised to one shape, and anything unusable reads as the root', () => {
  assert.equal(normalizeBase(''), '');
  assert.equal(normalizeBase('/'), '');
  assert.equal(normalizeBase('///'), '');
  assert.equal(normalizeBase(undefined), '');
  assert.equal(normalizeBase(42), '', 'a misconfigured value must not become a path');
  assert.equal(normalizeBase('/apps/scheinman'), '/apps/scheinman');
  assert.equal(normalizeBase('apps/scheinman'), '/apps/scheinman');
  assert.equal(normalizeBase('/apps/scheinman/'), '/apps/scheinman');
  assert.equal(normalizeBase('  /a//b/  '), '/a/b');
});

test('with no base path every address is exactly what it is today', () => {
  for (const path of Object.keys(PAGES)) {
    assert.equal(withBase('', path), path);
    assert.equal(withoutBase('', path), path);
  }
  assert.equal(cookiePath(''), '/');
  assert.equal(movedFrom('/v2/inspect'), '/inspect');
});

test('under a prefix every address carries it, and the walk back is exact', () => {
  const base = '/apps/scheinman';
  assert.equal(withBase(base, '/'), base, 'the overview is the prefix itself, with no trailing slash');
  for (const path of Object.keys(PAGES)) {
    const address = withBase(base, path);
    assert.ok(address.startsWith(base), `${path} escaped the prefix`);
    assert.equal(withoutBase(base, address), path, `${address} does not walk back to ${path}`);
  }
  assert.equal(cookiePath(base), base, 'a cookie at / would be sent to every neighbour');
  assert.equal(movedFrom('/v2/inspect', base), `${base}/inspect`);
});

test('an address outside the prefix is not ours, and is never mistaken for one', () => {
  const base = '/apps/scheinman';
  assert.equal(withoutBase(base, '/'), null);
  assert.equal(withoutBase(base, '/inspect'), null, 'a neighbour route must not reach our router');
  assert.equal(withoutBase(base, '/apps'), null);
  assert.equal(withoutBase(base, '/apps/scheinmanx'), null, 'a prefix is a path, not a string');
  assert.equal(withoutBase(base, '/apps/scheinman-other/page'), null);
  assert.equal(withoutBase(base, base), '/');
});
