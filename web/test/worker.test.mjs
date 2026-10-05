// The request handling itself, driven with a fake platform (audit 2026-09-02).
// Every rule in logic.mjs has its own test; these prove the WIRING:
// the door locks, the callback is guarded, a refused dispatch is honest, the
// watchdog fires on read and a late delivery still lands.
import assert from 'node:assert/strict';
import { test } from 'node:test';

import worker from '../src/worker.mjs';
import {
  ALERT_KEY,
  GATE_ATTEMPTS_PER_HOUR,
  MAX_UPLOAD_BYTES,
  newTicket,
  PAGES,
  SESSION_HOURS,
  SESSION_MAX_HOURS,
  ticketBorn,
  STALE_AFTER_MS,
  ticketValid,
} from '../src/logic.mjs';

const PASSWORD = 'Correct Horse 12%';
const ENGINE = 'engine-secret-for-tests';
const OWNER = 'owner-key-for-tests';

/** A Durable Object namespace whose objects live in a Map, one per name. */
function fakeNamespace(makeObject) {
  const objects = new Map();
  return {
    idFromName: (name) => name,
    get(name) {
      if (!objects.has(name)) objects.set(name, makeObject());
      return objects.get(name);
    },
  };
}

function fakeJobState() {
  let job = null;
  return {
    async fetch(url, init = {}) {
      if (init.method === 'PUT') { job = JSON.parse(init.body); return new Response('{"ok":true}'); }
      return job ? new Response(JSON.stringify(job)) : new Response('null', { status: 404 });
    },
  };
}

function fakeGateCounter() {
  let count = 0;
  return {
    async fetch(url, init = {}) {
      if (init.method === 'POST' && new URL(url).pathname === '/reset') { count = 0; }
      else if (init.method === 'POST') { count += 1; }
      return new Response(JSON.stringify({ count }));
    },
  };
}

function fakeKV() {
  const store = new Map();
  return {
    store,
    async get(key, type) {
      if (!store.has(key)) return null;
      const value = store.get(key);
      if (type === 'json') return JSON.parse(value);
      if (type === 'arrayBuffer') return value;
      return value;
    },
    async put(key, value) { store.set(key, value); },
    async list({ prefix }) {
      const keys = [...store.keys()].filter((k) => k.startsWith(prefix)).sort().map((name) => ({ name }));
      return { keys, list_complete: true };
    },
  };
}

const PAGES_FIXTURE = { '/home': '<!doctype html><title>SCHEINMAN Overview</title>', '/gate': '<!doctype html><p class="role">Sign in</p>', '/inspect': '<title>SCHEINMAN Inspect a part</title>', '/build.json': '{"commit":"abc123","built_at":"2026-09-02T00:00:00Z","tree":"clean"}' };

function makeEnv(overrides = {}) {
  return {
    SITE_PASSWORD: PASSWORD,
    ENGINE_SECRET: ENGINE,
    OWNER_KEY: OWNER,
    GITHUB_TOKEN: 'token',
    ENGINE_REPO: 'owner/repo',
    SITE_ORIGIN: 'https://counter.test',
    TURNSTILE_SECRET: '',
    LOCAL_DEV: 'true',
    JOBS: fakeKV(),
    JOB_STATE: fakeNamespace(fakeJobState),
    GATE_COUNT: fakeNamespace(fakeGateCounter),
    ASSETS: { async fetch(request) { const path = new URL(request.url).pathname; return path in PAGES_FIXTURE ? new Response(PAGES_FIXTURE[path]) : new Response('', { status: 404 }); } },
    ...overrides,
  };
}

const call = (env, path, init = {}) => worker.fetch(new Request(`https://counter.test${path}`, init), env);
const gatePost = (env, password, extra = {}) =>
  call(env, '/api/gate', { method: 'POST', headers: { 'content-type': 'application/json', ...extra }, body: JSON.stringify({ password }) });

async function login(env) {
  const r = await gatePost(env, PASSWORD);
  assert.equal(r.status, 200);
  return { cookie: r.headers.get('set-cookie').split(';')[0] };
}

function stepFile(name = 'bracket.step') {
  const bytes = new TextEncoder().encode('ISO-10303-21;\nHEADER;\nENDSEC;\nDATA;\nENDSEC;\nEND-ISO-10303-21;\n');
  return new File([bytes], name, { type: 'application/octet-stream' });
}

async function upload(env, cookie, file = stepFile()) {
  const body = new FormData();
  body.append('part', file);
  body.append('material_series', '7xxx');
  body.append('loading', 'cyclic');
  body.append('turnstile_token', '');
  return call(env, '/api/jobs', { method: 'POST', headers: { cookie }, body });
}

test('a stranger meets the door on every page and a refusal on every API route', async () => {
  const env = makeEnv();
  for (const path of ['/', '/inspect', '/archive', '/evidence', '/nowhere', '/v2', '/v2/inspect']) {
    const r = await call(env, path);
    assert.match(await r.text(), /role">Sign in/, path);
    assert.equal(r.headers.get('x-frame-options'), 'DENY');
    assert.equal(r.headers.get('cache-control'), 'no-store');
  }
  const api = await call(env, '/api/archive');
  assert.equal(api.status, 401);
  assert.equal(api.headers.get('x-content-type-options'), 'nosniff');
});

test('the door counts every wrong password, locks on the eleventh, and a burst cannot slip past', async () => {
  const env = makeEnv();
  for (let i = 1; i <= GATE_ATTEMPTS_PER_HOUR; i += 1) {
    const r = await gatePost(env, 'wrong');
    assert.equal(r.status, 401);
    const said = (await r.json()).error;
    if (i < GATE_ATTEMPTS_PER_HOUR) assert.match(said, new RegExp(`${GATE_ATTEMPTS_PER_HOUR - i} attempts? left`));
    else assert.match(said, /No attempts left/);
  }
  const locked = await gatePost(env, 'wrong');
  assert.equal(locked.status, 429);
  assert.match((await locked.json()).error, /reopens at \d\d:00 UTC/);
  assert.equal((await gatePost(env, PASSWORD)).status, 429, 'even the right password waits once locked');

  const fresh = makeEnv();
  const burst = await Promise.all(Array.from({ length: 30 }, () => gatePost(fresh, 'wrong')));
  const compared = burst.filter((r) => r.status === 401).length;
  assert.equal(compared, GATE_ATTEMPTS_PER_HOUR, 'a parallel burst gets exactly ten comparisons');
});

test('the right password opens the door, the site answers, and signing out closes it again', async () => {
  const env = makeEnv();
  const { cookie } = await login(env);
  const home = await call(env, '/', { headers: { cookie } });
  assert.match(await home.text(), /Overview/);
  const lock = await call(env, '/api/gate/lock', { method: 'POST', headers: { cookie } });
  assert.match(lock.headers.get('set-cookie'), /scheinman_gate=; .*Max-Age=0/);
  const stranger = await call(env, '/api/gate/lock', { method: 'POST' });
  assert.equal(stranger.status, 401, 'a stranger cannot even reach the lock');
  const dead = await call(env, '/api/archive', { headers: { cookie: 'scheinman_gate=1.dead' } });
  assert.match((await dead.json()).error, /Your session ended/);
});

/* The owner opened the site on 2026-09-11, was let straight in by a ticket the
   browser had kept for days, and read that as a site with no door: "it must
   always ask for the password, ALWAYS". Two things carry that order, and a regression in
   either one puts him back inside without typing anything.

   2026-09-20, the other half of the same order: the door must never interrupt
   someone who is reading. The half hour became half an hour of silence rather
   than half an hour of use (the renewal is the test below this one), and the
   cookie stayed a session cookie, which is what always asks again. */
test('the ticket goes idle in fifteen minutes and dies for good in two hours', async () => {
  const env = makeEnv();
  const answer = await gatePost(env, PASSWORD);
  const cookie = answer.headers.get('set-cookie');

  // 1. A session cookie: no Max-Age and no Expires, so it is never written to
  //    disk. It is not a guarantee on its own, because a browser set to
  //    restore its session brings session cookies back (2026-09-20), which is
  //    why the two limits below are what the order actually rests on.
  assert.doesNotMatch(cookie, /Max-Age/i, 'the ticket is written to disk and survives the browser');
  assert.doesNotMatch(cookie, /Expires/i, 'the ticket is written to disk and survives the browser');
  assert.match(cookie, /HttpOnly/);
  assert.match(cookie, /Secure/);

  // 2. Fifteen minutes of nobody touching the site, counted from the last
  //    request answered, so it catches a visitor who walked away and never one
  //    who is reading.
  assert.equal(SESSION_HOURS, 0.25, 'the ticket outlives the visit it was issued for');
  const now = Date.now();
  const ticket = await newTicket(PASSWORD, now, crypto.subtle, SESSION_HOURS, '');
  assert.equal(await ticketValid(ticket, PASSWORD, now + 14 * 60_000), true, 'it died during the visit');
  assert.equal(await ticketValid(ticket, PASSWORD, now + 16 * 60_000), false, 'it outlived the idle window');

  // 3. And a ceiling the sliding window cannot push. A ticket born two hours
  //    ago is refused however fresh its idle window looks.
  assert.equal(SESSION_MAX_HOURS, 2);
  const old = await newTicket(PASSWORD, now, crypto.subtle, SESSION_HOURS, '', now - 3 * 60 * 60_000);
  assert.equal(await ticketValid(old, PASSWORD, now), false, 'a ticket can be renewed for ever');
});

test('renewing carries the birth time, so the ceiling cannot be pushed away', async () => {
  const env = makeEnv();
  const { cookie } = await login(env);
  const born = ticketBorn(cookie);
  assert.ok(born && Math.abs(Date.now() - born) < 5000, 'the ticket must say when it was born');
  await new Promise((resolve) => setTimeout(resolve, 5));
  const answer = await call(env, '/inspect', { headers: { cookie } });
  const renewal = answer.headers.get('set-cookie');
  assert.equal(ticketBorn(renewal), born, 'the renewal restarted the two-hour ceiling');
});

test('an answer to someone inside carries a fresh ticket; a stranger is given none', async () => {
  const env = makeEnv();
  const { cookie } = await login(env);
  const issued = Number(cookie.match(/scheinman_gate=(\d+)\./)[1]);
  await new Promise((resolve) => setTimeout(resolve, 5));

  const answer = await call(env, '/inspect', { headers: { cookie } });
  const renewal = answer.headers.get('set-cookie');
  assert.ok(renewal, 'reading a page from inside must push the door further away');
  assert.doesNotMatch(renewal, /Max-Age/i, 'renewing must not turn it into a stored cookie');
  assert.doesNotMatch(renewal, /Expires/i, 'renewing must not turn it into a stored cookie');
  assert.match(renewal, /HttpOnly/);
  assert.match(renewal, /Secure/);
  assert.ok(
    Number(renewal.match(/scheinman_gate=(\d+)\./)[1]) > issued,
    'the renewed ticket has to die later than the one it replaces',
  );

  const stranger = await call(env, '/inspect');
  assert.equal(stranger.headers.get('set-cookie'), null, 'the door hands nobody a ticket');
});

/* One site again (owner chose the section view, 2026-09-11). The addresses
   version 2 answered for a day were shared, so they forward instead of 404. */
test('the site answers on its addresses, the retired ones forward, and a mistype lands on the map', async () => {
  const env = makeEnv();
  const { cookie } = await login(env);
  const home = await call(env, '/', { headers: { cookie } });
  assert.match(await home.text(), /Overview/, 'the overview answers at the root');
  const counter = await call(env, '/inspect', { headers: { cookie } });
  assert.match(await counter.text(), /Inspect a part/);

  const moved = await call(env, '/v2/inspect', { headers: { cookie } });
  assert.equal(moved.status, 301, 'a link someone already sent must not break');
  assert.equal(moved.headers.get('location'), '/inspect');
  const movedHome = await call(env, '/v2', { headers: { cookie } });
  assert.equal(movedHome.status, 301);
  assert.equal(movedHome.headers.get('location'), '/');

  const lost = await call(env, '/nowhere', { headers: { cookie } });
  assert.equal(lost.status, 404);
  assert.match(await lost.text(), /Overview/, 'a mistyped address lands on the map of what exists');
  const lostUnderV2 = await call(env, '/v2/nowhere', { headers: { cookie } });
  assert.equal(lostUnderV2.status, 404, 'a retired address that never existed is still a 404');
});

test('an oversized declaration is refused before the body is read', async () => {
  const env = makeEnv();
  const { cookie } = await login(env);
  const r = await call(env, '/api/jobs', { method: 'POST', headers: { cookie, 'content-length': String(MAX_UPLOAD_BYTES * 2) }, body: 'x' });
  assert.equal(r.status, 413);
  assert.match((await r.json()).error, /over the 10 MB/);
});

test('a part the engine accepts is queued, and a refused dispatch is honest and charges no run', async () => {
  const env = makeEnv();
  const { cookie } = await login(env);
  const realFetch = globalThis.fetch;
  let dispatchStatus = 204;
  globalThis.fetch = async (url) => (String(url).includes('api.github.com') && dispatchStatus === 204
    ? new Response(null, { status: 204 })
    : new Response('', { status: 500 }));
  try {
    const ok = await upload(env, cookie);
    assert.equal(ok.status, 202);
    const job = await ok.json();
    assert.equal(job.status, 'queued');
    assert.match(job.id, /^[0-9a-f]{32}$/);
    assert.equal([...env.JOBS.store.keys()].some((k) => k.startsWith('rate:global:')), true, 'everyone shares one daily ceiling');
    assert.equal([...env.JOBS.store.keys()].some((k) => k.startsWith('rate:') && !k.startsWith('rate:global:')), false, 'the owner is not charged a personal run');

    dispatchStatus = 500;
    const refused = await upload(env, cookie);
    assert.equal(refused.status, 502);
    const answer = await refused.json();
    assert.match(answer.error, /could not be started .*no run was spent/);
    assert.equal(answer.status, 'error');
  } finally {
    globalThis.fetch = realFetch;
  }
});

test('the counter closes when the human check is not configured, instead of waving everyone through', async () => {
  const env = makeEnv({ LOCAL_DEV: undefined });
  const { cookie } = await login(env);
  const r = await upload(env, cookie);
  assert.equal(r.status, 503);
  assert.match((await r.json()).error, /not configured/);
});

test('the callback is guarded by the engine key and never walks a job backwards', async () => {
  const env = makeEnv();
  const { cookie } = await login(env);
  const realFetch = globalThis.fetch;
  globalThis.fetch = async () => new Response(null, { status: 204 });
  let id;
  try { id = (await (await upload(env, cookie)).json()).id; } finally { globalThis.fetch = realFetch; }
  const forged = await call(env, `/api/jobs/${id}/callback`, { method: 'POST', headers: { 'x-scheinman-engine': 'nope', 'content-type': 'application/json' }, body: JSON.stringify({ status: 'clean' }) });
  assert.equal(forged.status, 401);
  const engine = { 'x-scheinman-engine': ENGINE, 'content-type': 'application/json' };
  const running = await call(env, `/api/jobs/${id}/callback`, { method: 'POST', headers: engine, body: JSON.stringify({ status: 'running', run_id: '1' }) });
  assert.equal((await running.json()).status, 'running');
  const done = await call(env, `/api/jobs/${id}/callback`, { method: 'POST', headers: engine, body: JSON.stringify({ status: 'clean', result: { violations: [], files: {} } }) });
  assert.equal((await done.json()).status, 'clean');
  const late = await call(env, `/api/jobs/${id}/callback`, { method: 'POST', headers: engine, body: JSON.stringify({ status: 'queued' }) });
  assert.equal((await late.json()).ignored, true);
  const read = await call(env, `/api/jobs/${id}`, { headers: { cookie } });
  assert.equal((await read.json()).status, 'clean');
});

test('a job the engine never came back for is declared dead on read, and a late delivery still lands', async () => {
  const env = makeEnv();
  const { cookie } = await login(env);
  const realFetch = globalThis.fetch;
  globalThis.fetch = async () => new Response(null, { status: 204 });
  let id;
  try { id = (await (await upload(env, cookie)).json()).id; } finally { globalThis.fetch = realFetch; }
  // Age the record: the fake object hands back whatever was stored.
  const stub = env.JOB_STATE.get(`job:${id}`);
  const stored = await (await stub.fetch('https://job/state')).json();
  stored.created_at = new Date(Date.now() - STALE_AFTER_MS - 1000).toISOString();
  await stub.fetch('https://job/state', { method: 'PUT', body: JSON.stringify(stored) });

  const read = await call(env, `/api/jobs/${id}`, { headers: { cookie } });
  const dead = await read.json();
  assert.equal(dead.status, 'error');
  assert.match(dead.reason, /did not report back/);
  const engine = { 'x-scheinman-engine': ENGINE, 'content-type': 'application/json' };
  const delivery = await call(env, `/api/jobs/${id}/callback`, { method: 'POST', headers: engine, body: JSON.stringify({ status: 'corrected', result: { violations: [], files: {} } }) });
  assert.equal((await delivery.json()).status, 'corrected', 'the truth about the part replaces the watchdog verdict');
  const again = await call(env, `/api/jobs/${id}`, { headers: { cookie } });
  assert.equal((await again.json()).status, 'corrected');
});

test('the health line opens to the engine key and the owner, counts only, and the version names the build', async () => {
  const env = makeEnv();
  assert.equal((await call(env, '/api/health')).status, 401);
  const withEngine = await call(env, '/api/health', { headers: { 'x-scheinman-engine': ENGINE } });
  assert.deepEqual(await withEngine.json(), { jobs_24h: 0, errors_24h: 0, stalled: 0, last_job_at: null, healthy: true });
  const { cookie } = await login(env);
  assert.equal((await (await call(env, '/api/version', { headers: { cookie } })).json()).commit, 'abc123');
  const archive = await call(env, '/api/archive', { headers: { 'x-scheinman-owner': OWNER } });
  assert.deepEqual((await archive.json()).jobs, []);
});

test('a page missing from the build is a loud failure, never an empty success', async () => {
  const env = makeEnv({ ASSETS: { async fetch() { return new Response('', { status: 404 }); } } });
  const { cookie } = await login(env);
  const r = await call(env, '/', { headers: { cookie } });
  assert.equal(r.status, 500);
  assert.match(await r.text(), /missing from the build/);
});

// --- The alarm (2026-09-03). GitHub's scheduled runs are best effort, so the
// counter watches itself on a Cloudflare cron and rings through a workflow that
// fails on purpose. These prove the wiring: when it rings, when it stays quiet,
// and that a refused ring is tried again instead of being swallowed.

function alarmEnv({ jobs = [], lastAlertAt = null, dispatchStatus = 204 } = {}) {
  const calls = [];
  const env = makeEnv();
  for (const [i, job] of jobs.entries()) {
    env.JOBS.store.set(`index:job:${i}`, JSON.stringify(job));
  }
  if (lastAlertAt) env.JOBS.store.set(ALERT_KEY, lastAlertAt);
  globalThis.fetch = async (url, init) => {
    calls.push({ url: String(url), body: JSON.parse(init.body) });
    return new Response(null, { status: dispatchStatus });
  };
  return { env, calls };
}

const deadJob = (created) => ({ id: 'a'.repeat(32), status: 'error', created_at: created, part_name: 'p' });
const stuckJob = (created) => ({ id: 'b'.repeat(32), status: 'queued', created_at: created, part_name: 'p' });

test('the alarm stays quiet while every job is healthy', async () => {
  const real = globalThis.fetch;
  const { env, calls } = alarmEnv({ jobs: [{ id: 'c'.repeat(32), status: 'corrected', created_at: new Date().toISOString(), part_name: 'p' }] });
  await worker.scheduled({}, env);
  globalThis.fetch = real;
  assert.equal(calls.length, 0);
  assert.equal(await env.JOBS.get(ALERT_KEY), null);
});

test('a dead job rings the alarm once and the ring is remembered', async () => {
  const real = globalThis.fetch;
  const { env, calls } = alarmEnv({ jobs: [deadJob(new Date().toISOString())] });
  await worker.scheduled({}, env);
  assert.equal(calls.length, 1);
  assert.match(calls[0].url, /workflows\/alert\.yml\/dispatches$/);
  assert.match(calls[0].body.inputs.reason, /1 job\(s\) died/);
  const stamped = await env.JOBS.get(ALERT_KEY);
  assert.ok(stamped, 'the ring must be remembered');
  // A second tick minutes later must not ring again.
  await worker.scheduled({}, env);
  globalThis.fetch = real;
  assert.equal(calls.length, 1);
});

test('a job stuck past the watchdog window rings too', async () => {
  const real = globalThis.fetch;
  const old = new Date(Date.now() - STALE_AFTER_MS - 60_000).toISOString();
  const { env, calls } = alarmEnv({ jobs: [stuckJob(old)] });
  await worker.scheduled({}, env);
  globalThis.fetch = real;
  assert.equal(calls.length, 1);
  assert.match(calls[0].body.inputs.reason, /stalled/);
});

test('a ring GitHub refuses is not remembered, so the next tick tries again', async () => {
  const real = globalThis.fetch;
  const { env, calls } = alarmEnv({ jobs: [deadJob(new Date().toISOString())], dispatchStatus: 500 });
  await worker.scheduled({}, env);
  assert.equal(calls.length, 1);
  assert.equal(await env.JOBS.get(ALERT_KEY), null);
  await worker.scheduled({}, env);
  globalThis.fetch = real;
  assert.equal(calls.length, 2, 'a refused ring must be retried');
});

// --- Lesson 023 (2026-09-03): the guided conference was built into the site and
// the router did not know its address, so the owner met a 404 on a page that
// existed. The builder and the router are bound together in
// tests/test_webbuild.py, which is the side that knows what gets built.
//
// The guided conference used to live at /conference2: a page of Portuguese
// asking the owner to judge 46 extracted facts by hand. He read it on
// 2026-09-20 and said the judging is the session's work, not his. The address
// is retired, and a retired address is not a hole in the door.

test('the retired conference address is gone, and still stands behind the door', async () => {
  const env = makeEnv();
  const stranger = await call(env, '/conference2');
  assert.equal(stranger.status, 200, 'a page address answers with the door itself');
  assert.match(await stranger.text(), /role">Sign in/, 'a stranger meets the door');
  const { cookie } = await login(env);
  const inside = await call(env, '/conference2', { headers: { cookie } });
  assert.equal(inside.status, 404, 'the address no longer exists, and says so');
  assert.match(await inside.text(), /SCHEINMAN Overview/, 'and shows what does exist');
});

// --- 2026-09-04: the owner could not get in. The door compared the password
// exactly, so a space pasted along with it, or a newline, read as a wrong
// password and spent one of the ten attempts an hour. Trimming cannot widen
// what opens the door; these prove both halves.

test('a password with whitespace around it still opens the door', async () => {
  const env = makeEnv();
  for (const value of [` ${PASSWORD}`, `${PASSWORD} `, `\n${PASSWORD}\n`, `\t${PASSWORD} `]) {
    const answer = await gatePost(env, value);
    assert.equal(answer.status, 200, `${JSON.stringify(value)} should open the door`);
  }
});

test('trimming does not open the door to a wrong password', async () => {
  const env = makeEnv();
  for (const value of [PASSWORD.toLowerCase(), `${PASSWORD}x`, PASSWORD.slice(0, -1), '   ']) {
    const answer = await gatePost(env, value);
    assert.equal(answer.status, 401, `${JSON.stringify(value)} must stay refused`);
  }
});

test('the refusal says what to do about a browser that filled the field', async () => {
  const env = makeEnv();
  const answer = await gatePost(env, 'not-the-password');
  const body = await answer.json();
  assert.match(body.error, /attempts left this hour/);
  assert.match(body.error, /clear it and type the password yourself/);
});

/* --- Serving under a prefix (shared-host mounting, 2026-09-15) -----------------------
   The same Worker, configured with a base path, answers there and nowhere
   else. These go through the real router, because the whole risk of a prefix
   is a route that half-knows about it. */

test('with a base path the site answers under it, and the door still stands in front', async () => {
  const base = '/apps/scheinman';
  const env = { ...makeEnv(), BASE_PATH: base };

  // A stranger meets the door at the prefixed address, not the site. A page
  // answers with the door itself; only a script's route gets a bare refusal.
  const closed = await call(env, `${base}/inspect`);
  assert.equal(closed.status, 200);
  assert.match(await closed.text(), /role">Sign in/);
  assert.equal((await call(env, `${base}/api/archive`)).status, 401);

  const answer = await call(env, `${base}/api/gate`, {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify({ password: PASSWORD }),
  });
  assert.equal(answer.status, 200);
  const setCookie = answer.headers.get('set-cookie');
  // The cookie is scoped to the app, or the ticket would be sent to every
  // other page on a shared hostname.
  assert.match(setCookie, new RegExp(`Path=${base}(;|$)`));
  const cookie = setCookie.split(';')[0];

  const home = await call(env, base, { headers: { cookie } });
  assert.equal(home.status, 200);
  assert.match(await home.text(), /Overview/);
  const counter = await call(env, `${base}/inspect`, { headers: { cookie } });
  assert.match(await counter.text(), /Inspect a part/);
});

test('with a base path, a neighbour address on the same hostname is not ours', async () => {
  const base = '/apps/scheinman';
  const env = { ...makeEnv(), BASE_PATH: base };
  // No cookie on purpose: an address outside the prefix must not even meet our
  // door, because the door is a page of this app and this is not its address.
  for (const path of ['/', '/inspect', '/api/gate', '/apps', '/apps/scheinmanx']) {
    const answer = await call(env, path);
    assert.equal(answer.status, 404, `${path} was answered as if it were ours`);
  }
});

test('the retired /v2 addresses forward inside the prefix, never out of it', async () => {
  const base = '/apps/scheinman';
  const env = { ...makeEnv(), BASE_PATH: base };
  const { cookie } = await (async () => {
    const r = await call(env, `${base}/api/gate`, {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ password: PASSWORD }),
    });
    return { cookie: r.headers.get('set-cookie').split(';')[0] };
  })();
  const moved = await call(env, `${base}/v2/inspect`, { headers: { cookie } });
  assert.equal(moved.status, 301);
  assert.equal(moved.headers.get('location'), `${base}/inspect`);
});

test('the version line says which prefix the build was made for and which one is served', async () => {
  // A build written for one prefix and routed under another is a site where
  // every link is dead and every page looks fine. The mismatch is readable
  // from outside, before anyone is sent to the address.
  const base = '/apps/scheinman';
  const env = { ...makeEnv(), BASE_PATH: base };
  const { cookie } = await (async () => {
    const r = await call(env, `${base}/api/gate`, {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ password: PASSWORD }),
    });
    return { cookie: r.headers.get('set-cookie').split(';')[0] };
  })();
  const version = await call(env, `${base}/api/version`, { headers: { cookie } });
  const stamp = await version.json();
  assert.equal(stamp.serving, base);
  assert.equal(stamp.base_path, '', 'the fixture build was made for the root');
  assert.equal(stamp.matches, false, 'a root build served under a prefix must not read as fine');
});
