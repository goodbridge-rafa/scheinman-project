// The counter's doorman. It receives the part, guards the door, hands the work
// to the engine, and serves the finished delivery back into the page. It never
// judges geometry: that is the engine's job, and the engine runs where a real
// CAD kernel lives (GitHub Actions), never here.
//
// Every rule this file applies comes from ./logic.mjs, where it is tested.

export { JobState } from './job_state.mjs';
export { GateCounter } from './gate_counter.mjs';

import {
  GATE_ATTEMPTS_PER_HOUR,
  MAX_UPLOAD_BYTES,
  GATE_COOKIE,
  SESSION_HOURS,
  ticketBorn,
  blobKey,
  canAdvance,
  dayStamp,
  gateAttemptKey,
  hourStamp,
  lockedMessage,
  wrongPasswordMessage,
  staleJob,
  newestFirst,
  lockCookie,
  cookiePath,
  SESSION_ENDED,
  countsAgainstDailyLimit,
  globalRateKey,
  globalRefusal,
  humanCheckMode,
  healthSummary,
  movedFrom,
  normalizeBase,
  PAGES,
  withBase,
  withoutBase,
  shouldAlert,
  ALERT_KEY,
  acceptsLateDelivery,
  MAX_UPLOAD_MB,
  indexEntry,
  indexKey,
  jobKey,
  linkExpired,
  newJob,
  newJobId,
  partNameFrom,
  publicView,
  needsGate,
  newTicket,
  rateKey,
  rateRefusal,
  readCookie,
  secretMatches,
  ticketValid,
  uploadRefusal,
  visitorBucket,
} from './logic.mjs';

/* Headers every response wears (audit 2026-09-02). Deliberately the
 * set that cannot break the page: nobody may frame this site, the base address
 * cannot be hijacked, plugins are off, browsers keep to the declared type and
 * to HTTPS, and other sites learn only the origin. Script, style and font
 * sources are NOT restricted here: the pages carry inline scripts and load
 * Google Fonts and the Turnstile widget, and a wrong list would break the
 * counter silently in a way no local test can see. */
const SECURITY_HEADERS = {
  'content-security-policy': "frame-ancestors 'none'; base-uri 'self'; object-src 'none'",
  'x-frame-options': 'DENY',
  'x-content-type-options': 'nosniff',
  'referrer-policy': 'strict-origin-when-cross-origin',
  'strict-transport-security': 'max-age=31536000; includeSubDomains',
  'permissions-policy': 'camera=(), microphone=(), geolocation=()',
};
const JSON_HEADERS = {
  ...SECURITY_HEADERS,
  'content-type': 'application/json; charset=utf-8',
  'cache-control': 'no-store',
};

const json = (body, status = 200) => new Response(JSON.stringify(body), { status, headers: JSON_HEADERS });
const fail = (message, status) => json({ error: message }, status);

const FILE_TYPES = {
  '.md': 'text/markdown; charset=utf-8',
  '.pdf': 'application/pdf',
  '.step': 'model/step',
  '.json': 'application/json; charset=utf-8',
};

/** Cloudflare's verdict on a human-check token, and where it was solved.
 *
 * Success alone was enough while this site owned its hostname. Moving under a
 * prefix on a shared site means the same sitekey is valid on a hostname other
 * pages also serve (shared-host mounting, 2026-09-15), so a token solved on a widget
 * embedded elsewhere would verify here too. When TURNSTILE_HOSTNAMES is set,
 * the hostname Cloudflare reports has to be one of them. Unset keeps the old
 * behaviour, so the deployment that is live today is unaffected.
 */
async function turnstilePassed(token, ip, secret, allowed = '') {
  const body = new FormData();
  body.append('secret', secret);
  body.append('response', token ?? '');
  if (ip) body.append('remoteip', ip);
  const verdict = await fetch('https://challenges.cloudflare.com/turnstile/v0/siteverify', {
    method: 'POST',
    body,
    signal: AbortSignal.timeout(10_000),
  });
  const outcome = await verdict.json();
  if (outcome.success !== true) return false;
  const names = String(allowed)
    .split(',')
    .map((name) => name.trim().toLowerCase())
    .filter(Boolean);
  if (!names.length) return true;
  return names.includes(String(outcome.hostname ?? '').toLowerCase());
}

class HumanCheckUnavailable extends Error {}

/** The verdict, or a named failure when Cloudflare's service did not answer:
 * the visitor is told nothing was started, instead of a generic crash. */
async function humanCheckPassed(token, ip, secret, allowed = '') {
  try {
    return await turnstilePassed(token, ip, secret, allowed);
  } catch (error) {
    throw new HumanCheckUnavailable(String(error?.message ?? error));
  }
}

/** Ask GitHub Actions to run this job. The engine is the same machine the
 * repository's own checks run on, so what the counter serves is what the
 * project proves green on every commit. */
async function startEngine(env, job, origin) {
  const response = await fetch(
    `https://api.github.com/repos/${env.ENGINE_REPO}/actions/workflows/analyze.yml/dispatches`,
    {
      method: 'POST',
      headers: {
        authorization: `Bearer ${env.GITHUB_TOKEN}`,
        accept: 'application/vnd.github+json',
        'x-github-api-version': '2022-11-28',
        'user-agent': 'scheinman-web',
        'content-type': 'application/json',
      },
      body: JSON.stringify({ ref: 'main', inputs: { job_id: job.id, base_url: origin } }),
      signal: AbortSignal.timeout(15_000),
    },
  );
  if (response.status !== 204) {
    throw new Error(`the engine did not accept the job (GitHub answered ${response.status})`);
  }
}

/** The job's own Durable Object: one place per job, read-after-write. */
function jobStub(env, id) {
  return env.JOB_STATE.get(env.JOB_STATE.idFromName(jobKey(id)));
}

async function readJob(env, id) {
  if (!/^[0-9a-f]{32}$/.test(id)) return null;
  const answer = await jobStub(env, id).fetch('https://job/state');
  return answer.ok ? await answer.json() : null;
}

async function writeJob(env, job) {
  await jobStub(env, job.id).fetch('https://job/state', {
    method: 'PUT',
    body: JSON.stringify(job),
    headers: { 'content-type': 'application/json' },
  });
  // The archive index, kept beside the job so the owner's page can list what
  // exists without opening every job (decision 2026-09-01: nothing is deleted
  // when a visitor's link closes).
  await env.JOBS.put(indexKey(job), JSON.stringify(indexEntry(job)));
}

/** The owner, reading their own archive. Two ways in, on purpose:
 *  - the owner key in a header, which is what a script or another machine uses
 *    and is separate from the engine's, so an engine secret in a workflow log
 *    never opens the archive;
 *  - a valid door ticket, because while the site is password-gated the only
 *    person past the door IS the owner. The moment the password is removed,
 *    SITE_PASSWORD is unset, no ticket can be valid, and only the key works. */
async function isOwner(request, env) {
  if (secretMatches(request.headers.get('x-scheinman-owner'), env.OWNER_KEY)) return true;
  if (!env.SITE_PASSWORD) return false;
  const ticket = readCookie(request.headers.get('cookie'), GATE_COOKIE);
  return await ticketValid(ticket, env.SITE_PASSWORD, Date.now(), crypto.subtle, env.TICKET_KEY ?? '');
}

const ARCHIVE_PAGE = 200;

/** Every job ever run, newest first. KV lists keys oldest first, so a single
 * capped listing would keep the OLDEST page and lose the newest (audit
 * 2026-09-02): walk every key, then take the newest page. */
async function archiveKeys(env) {
  const keys = [];
  let cursor;
  for (let pages = 0; pages < 20; pages += 1) {
    const list = await env.JOBS.list({ prefix: 'index:', limit: 1000, cursor });
    keys.push(...list.keys.map((k) => k.name));
    if (list.list_complete !== false) break;
    cursor = list.cursor;
  }
  return keys;
}

async function archiveEntries(env, names) {
  const wanted = names ?? (await archiveKeys(env));
  const entries = await Promise.all(wanted.map((name) => env.JOBS.get(name, 'json')));
  return entries.filter(Boolean);
}

async function listArchive(env, url) {
  const keys = await archiveKeys(env);
  const newest = keys.slice(Math.max(0, keys.length - ARCHIVE_PAGE));
  return json({
    jobs: newestFirst(await archiveEntries(env, newest), ARCHIVE_PAGE),
    total: keys.length,
    more: keys.length > ARCHIVE_PAGE,
    counter: url.origin,
  });
}


/* ---------------------------------------------------------------------------
 * The door. Until the owner opens the site to everyone, one password stands in
 * front of every page and every visitor route. The engine and the owner carry
 * their own keys in a header and go around it, because a machine cannot type a
 * password and stranding a running job would be worse than any gate.
 * ------------------------------------------------------------------------- */

/* No Max-Age on purpose (owner's order, 2026-09-11): a session cookie is held
 * in memory and dies when the browser closes, so the next visit meets the door.
 * The ticket inside it carries its own expiry as well, which is what stops a
 * tab left open all afternoon from staying inside. */
/* Path is the app's own base, never "/" when there is a prefix: on a shared
 * hostname a cookie scoped to the root is sent to every neighbour there
 * (shared-host mounting, 2026-09-15). */
const cookieHeader = (ticket, base) =>
  `${GATE_COOKIE}=${ticket}; Path=${cookiePath(base)}; HttpOnly; Secure; SameSite=Lax`;

async function handleGate(request, env, url, base) {
  const now = Date.now();
  const ip = request.headers.get('cf-connecting-ip') ?? '0.0.0.0';
  const hour = hourStamp(now);
  // One counter object per visitor and hour; it serialises its own requests,
  // so ten guesses fired at once are ten, never one (gate_counter.mjs).
  const counter = env.GATE_COUNT.get(env.GATE_COUNT.idFromName(gateAttemptKey(await visitorBucket(ip, hour), hour)));
  // Count this attempt first, then decide: a burst of guesses fired together
  // is refused past the tenth, whatever order they land in (audit 2026-09-02).
  // A right password clears the count: a person who typed it does not
  // lock themselves out by logging in often.
  const { count } = await (await counter.fetch('https://gate/count', { method: 'POST' })).json();
  if (count > GATE_ATTEMPTS_PER_HOUR) {
    return fail(lockedMessage(now), 429);
  }
  const body = await request.json().catch(() => ({}));
  // Trim before comparing: a password pasted from a message or filled by a
  // browser often carries a space or a newline, and an invisible character is
  // not a wrong password (the owner was locked out by one on 2026-09-04).
  // Trimming can never widen what opens the door: the stored password has no
  // edge whitespace, and a test proves the door still refuses a wrong value.
  if (!secretMatches(String(body.password ?? '').trim(), env.SITE_PASSWORD)) {
    console.log('gate: refused, attempt', count, 'of', GATE_ATTEMPTS_PER_HOUR);
    return fail(wrongPasswordMessage(count, now), 401);
  }
  console.log('gate: opened');
  await counter.fetch('https://gate/reset', { method: 'POST' });
  const ticket = await newTicket(env.SITE_PASSWORD, now, crypto.subtle, SESSION_HOURS, env.TICKET_KEY ?? '');
  return new Response(JSON.stringify({ ok: true }), {
    status: 200,
    headers: { ...JSON_HEADERS, 'set-cookie': cookieHeader(ticket, base) },
  });
}

/** Everyone who is past the door, and how they got there:
 *  - no password configured at all: the site is open to the world;
 *  - the engine's key, because a workflow cannot type a password and a job
 *    half-way through must never be locked out of its own counter;
 *  - the owner's key, for a script or another machine;
 *  - a valid ticket from the door itself, which is how a person gets in. */
async function pastTheGate(request, env) {
  if (!env.SITE_PASSWORD) return true;
  if (secretMatches(request.headers.get('x-scheinman-engine'), env.ENGINE_SECRET)) return true;
  if (secretMatches(request.headers.get('x-scheinman-owner'), env.OWNER_KEY)) return true;
  const ticket = readCookie(request.headers.get('cookie'), GATE_COOKIE);
  return await ticketValid(ticket, env.SITE_PASSWORD, Date.now(), crypto.subtle, env.TICKET_KEY ?? '');
}

/** The owner locking the door behind them: the ticket cookie is emptied and
 * expired, and the next page load asks for the password again. */
function lockDoor(base) {
  return new Response(JSON.stringify({ ok: true }), {
    status: 200,
    headers: { ...JSON_HEADERS, 'set-cookie': lockCookie(base) },
  });
}

/** What someone sees before the password: the door itself for a page, a plain
 * refusal for anything a script asked for. A person who WAS inside and whose
 * ticket died (seven days, or a rotated password) is told that, not that the
 * site is closed (audit 2026-09-02). */
async function closedDoor(request, env, url, path) {
  // The path WITHOUT the base, because under a prefix the raw pathname starts
  // with that prefix and no API route would ever be recognised: a script's
  // request would be answered with the door's HTML and a 200.
  if (path.startsWith('/api/')) {
    const hadTicket = Boolean(readCookie(request.headers.get('cookie'), GATE_COOKIE));
    return fail(hadTicket ? SESSION_ENDED : 'This site is not open yet.', 401);
  }
  return page(request, env, url, 'gate');
}

/** Serve one of the site's built pages, whatever address asked for it. */
async function page(request, env, url, name, status = 200) {
  const asset = await env.ASSETS.fetch(new Request(new URL(`/${name}`, url), request));
  if (!asset.ok) {
    console.error('SCHEINMAN ALERT: page missing from the build', name, asset.status);
    return new Response('This page is missing from the build. The owner has been told.', {
      status: 500,
      headers: { ...SECURITY_HEADERS, 'content-type': 'text/plain; charset=utf-8', 'cache-control': 'no-store' },
    });
  }
  return new Response(asset.body, {
    status,
    headers: { ...SECURITY_HEADERS, 'content-type': 'text/html; charset=utf-8', 'cache-control': 'no-store' },
  });
}

async function handleUpload(request, env, url, base) {
  // Refuse on the declared size before reading the body. formData() buffers the
  // whole upload, and a worker has far less memory than the platform's request
  // limit, so the size check has to happen before the read, not after it.
  const declared = Number(request.headers.get('content-length') ?? 0);
  if (declared > MAX_UPLOAD_BYTES + 64 * 1024) {
    return fail(`That is over the ${MAX_UPLOAD_MB} MB the counter takes.`, 413);
  }
  const form = await request.formData();
  const file = form.get('part');
  if (!(file instanceof File)) return fail('Attach the part as the field "part".', 400);
  const bytes = new Uint8Array(await file.arrayBuffer());
  const materialSeries = String(form.get('material_series') ?? '');
  const loading = String(form.get('loading') ?? '');

  const refusal = uploadRefusal({ filename: file.name, bytes, materialSeries, loading });
  if (refusal) return fail(refusal, 400);

  const ip = request.headers.get('cf-connecting-ip') ?? '0.0.0.0';
  const mode = humanCheckMode(env.TURNSTILE_SECRET, env.LOCAL_DEV);
  if (mode === 'closed') {
    console.error('SCHEINMAN ALERT: TURNSTILE_SECRET is not configured; the counter is closed');
    return fail('The human check is not configured on this counter, so it is closed for now. The owner has been told.', 503);
  }
  if (mode === 'verify') {
    let passed;
    try {
      passed = await humanCheckPassed(
        form.get('turnstile_token'),
        ip,
        env.TURNSTILE_SECRET,
        env.TURNSTILE_HOSTNAMES ?? '',
      );
    } catch (error) {
      if (error instanceof HumanCheckUnavailable) {
        return fail('The anti-robot service did not answer. Nothing was started; try again in a minute.', 503);
      }
      throw error;
    }
    if (!passed) return fail('The anti-robot check did not pass. Reload the page and try again.', 403);
  }

  const now = Date.now();
  const day = dayStamp(now);
  const bucket = rateKey(await visitorBucket(ip, day), day);
  // The counter lives in KV, so two colos could each let a run through before
  // seeing the other's write. That is a courtesy cap, not the bot gate
  // (Turnstile is), and one extra run costs a minute of a free runner. The
  // owner is exempt: while the site is private the only person inside is the
  // owner, and a demo must not stop at the sixth part.
  const counted = countsAgainstDailyLimit(await isOwner(request, env));
  const spent = counted ? Number((await env.JOBS.get(bucket)) ?? 0) : 0;
  const overLimit = counted ? rateRefusal(spent) : null;
  if (overLimit) return fail(overLimit, 429);
  // Everyone together, owner included: the engine's free minutes are finite.
  const globalBucket = globalRateKey(day);
  const spentByAll = Number((await env.JOBS.get(globalBucket)) ?? 0);
  const overGlobal = globalRefusal(spentByAll);
  if (overGlobal) return fail(overGlobal, 429);

  const id = newJobId(crypto.getRandomValues(new Uint8Array(16)));
  const job = newJob({ id, partName: partNameFrom(file.name), materialSeries, loading, now });
  await env.JOBS.put(blobKey(id, 'submitted_step'), bytes);
  await writeJob(env, job);

  try {
    // The address the engine calls back on comes from configuration, not from
    // the request. The engine carries a secret in that call; a request must
    // never be able to choose where that secret is sent. Under a prefix the
    // callback has to carry it too, or the engine would post to a neighbour.
    await startEngine(env, job, `${env.SITE_ORIGIN || url.origin}${base}`);
  } catch (error) {
    // The part was fine; the engine could not be reached. Say exactly that,
    // keep the job as a reference, and do not charge the visitor a run.
    job.status = 'error';
    job.reason = String(error.message ?? error);
    job.finished_at = new Date(Date.now()).toISOString();
    await writeJob(env, job);
    return json(
      {
        error: `The engine could not be started (${job.reason}). Nothing was measured and no run was spent; try again in a few minutes.`,
        ...publicView(job),
      },
      502,
    );
  }
  // A run is spent once the engine has taken the part. A part that then crashes
  // the engine still counts: a failing part cannot be used to hammer the door.
  if (counted) await env.JOBS.put(bucket, String(spent + 1), { expirationTtl: 48 * 60 * 60 });
  await env.JOBS.put(globalBucket, String(spentByAll + 1), { expirationTtl: 48 * 60 * 60 });
  return json(publicView(job), 202);
}

async function handleFile(env, job, role) {
  const filename = job.result?.files?.[role];
  if (!filename) return fail('This delivery has no file in that role.', 404);
  const stored = await env.JOBS.get(blobKey(job.id, role), 'arrayBuffer');
  if (!stored) return fail('That file is not in the archive.', 404);
  const extension = filename.slice(filename.lastIndexOf('.'));
  return new Response(stored, {
    headers: {
      ...SECURITY_HEADERS,
      'content-type': FILE_TYPES[extension] ?? 'application/octet-stream',
      'content-disposition': `attachment; filename="${filename}"`,
      'cache-control': 'no-store',
    },
  });
}

/** The engine reports back here: first that it started, then the delivery. */
async function handleCallback(request, env, job) {
  if (!secretMatches(request.headers.get('x-scheinman-engine'), env.ENGINE_SECRET)) {
    return fail('not authorised', 401);
  }
  const payload = await request.json();
  const status = String(payload.status ?? '');
  if (!canAdvance(job.status, status) && !acceptsLateDelivery(job, status)) {
    // Not an error: retries and out-of-order messages are normal, and a
    // finished job must never be walked backwards.
    return json({ ignored: true, status: job.status });
  }
  job.status = status;
  delete job.watchdog;
  if (status === 'running') {
    job.started_at = new Date(Date.now()).toISOString();
    job.engine_run_id = payload.run_id ?? null;
  } else {
    job.finished_at = new Date(Date.now()).toISOString();
    job.result = payload.result ?? null;
    job.reason = payload.result?.reason ?? payload.reason ?? null;
    for (const [role, file] of Object.entries(payload.files ?? {})) {
      const bytes = Uint8Array.from(atob(file), (c) => c.charCodeAt(0));
      await env.JOBS.put(blobKey(job.id, role), bytes);
    }
  }
  await writeJob(env, job);
  return json({ ok: true, status: job.status });
}

/** The alarm. The counter watches itself on a Cloudflare cron (reliable) and
 * rings by asking GitHub to run a workflow that fails on purpose, because the
 * owner already gets an e-mail for a failed workflow. GitHub's own scheduled
 * runs are best effort: on 2026-09-03 an hourly cron fired four times in ten
 * hours, so they cannot be the only alarm (lesson 022). watch.yml stays, once a
 * day, as the outside observer: this handler cannot report its own Worker being
 * down. */
async function ringAlarm(env, reason) {
  const response = await fetch(
    `https://api.github.com/repos/${env.ENGINE_REPO}/actions/workflows/alert.yml/dispatches`,
    {
      method: 'POST',
      headers: {
        authorization: `Bearer ${env.GITHUB_TOKEN}`,
        accept: 'application/vnd.github+json',
        'x-github-api-version': '2022-11-28',
        'user-agent': 'scheinman-web',
        'content-type': 'application/json',
      },
      body: JSON.stringify({ ref: 'main', inputs: { reason } }),
      signal: AbortSignal.timeout(15_000),
    },
  );
  return response.status === 204;
}

export default {
  async scheduled(controller, env) {
    const now = Date.now();
    const summary = healthSummary(await archiveEntries(env), now);
    const lastAlertAt = await env.JOBS.get(ALERT_KEY);
    const { ring, reason } = shouldAlert(summary, lastAlertAt, now);
    if (!ring) return;
    // Write the stamp only when GitHub accepted the call, so a refused ring is
    // tried again on the next tick instead of being silently swallowed.
    if (await ringAlarm(env, reason)) await env.JOBS.put(ALERT_KEY, new Date(now).toISOString());
  },

  /* Every answer to someone who is already inside carries a fresh ticket, so
   * the half hour in SESSION_HOURS is half an hour of NOT using the site
   * rather than half an hour of using it (owner, 2026-09-20: the door must
   * never interrupt a reader, and must always be there after the browser is
   * closed). The cookie stays a session cookie, so closing the browser still
   * throws the ticket away. A renewal is skipped when the answer already sets
   * the cookie itself, which is the door opening and the owner locking it. */
  async fetch(request, env) {
    const base = normalizeBase(env.BASE_PATH ?? '');
    const ticket = readCookie(request.headers.get('cookie'), GATE_COOKIE);
    const inside =
      Boolean(env.SITE_PASSWORD) &&
      (await ticketValid(ticket, env.SITE_PASSWORD, Date.now(), crypto.subtle, env.TICKET_KEY ?? ''));
    const response = await route(request, env, base);
    if (!inside || response.headers.has('set-cookie')) return response;
    const renewed = new Response(response.body, response);
    // The renewal carries the original birth time forward, so the sliding
    // window can never push the two-hour ceiling out in front of it.
    renewed.headers.set(
      'set-cookie',
      cookieHeader(
        await newTicket(
          env.SITE_PASSWORD,
          Date.now(),
          crypto.subtle,
          SESSION_HOURS,
          env.TICKET_KEY ?? '',
          ticketBorn(ticket) ?? Date.now(),
        ),
        base,
      ),
    );
    return renewed;
  },
};

async function route(request, env, base) {
    const url = new URL(request.url);
    // Everything below reasons about the path as if this app owned the root,
    // which is what it did until central hosting asked for a prefix on a shared
    // site (shared-host mounting, 2026-09-15). The prefix is taken off once, here, so one
    // line decides it instead of every route. BASE_PATH unset means the root
    // and the behaviour that is live today.
    const path = withoutBase(base, url.pathname);
    // Not ours. On a shared hostname the neighbours' addresses reach this
    // Worker too, and answering them with our door would be a surprise.
    if (path === null) return fail('not found', 404);

    if (path === '/api/gate' && request.method === 'POST') return handleGate(request, env, url, base);
    if (needsGate(path) && !(await pastTheGate(request, env))) {
      return closedDoor(request, env, url, path);
    }
    if (path === '/api/gate/lock' && request.method === 'POST') return lockDoor(base);

    if (path === '/api/jobs' && request.method === 'POST') return handleUpload(request, env, url, base);

    if (path === '/api/archive' && request.method === 'GET') {
      return (await isOwner(request, env)) ? listArchive(env, url) : fail('not authorised', 401);
    }
    if (path === '/api/version' && request.method === 'GET') {
      const asset = await env.ASSETS.fetch(new Request(new URL('/build.json', url), request));
      if (!asset.ok) return fail('this build carries no stamp', 500);
      const stamp = await asset.json();
      // The pages were written with a prefix baked into every address they
      // carry, and this Worker routes with the prefix it is configured for. If
      // the two disagree the site looks fine and every link is dead, so the
      // mismatch is stated here, where the publisher can read it from outside
      // before sending anyone to the address.
      const built = normalizeBase(stamp.base_path ?? '');
      return json({ ...stamp, base_path: built, serving: base, matches: built === base });
    }
    if (path === '/api/health' && request.method === 'GET') {
      // Counts only, for the six-hourly watch: the engine's key opens this line
      // and nothing more (no part names, no files).
      const engine = secretMatches(request.headers.get('x-scheinman-engine'), env.ENGINE_SECRET);
      if (!engine && !(await isOwner(request, env))) return fail('not authorised', 401);
      return json(healthSummary(await archiveEntries(env), Date.now()));
    }

    const jobRoute = path.match(/^\/api\/jobs\/([0-9a-f]{32})(\/[a-z_/]+)?$/);
    if (jobRoute) {
      const [, id, tail] = jobRoute;
      let job = await readJob(env, id);
      if (!job) return fail('No job with that address. The link may be mistyped.', 404);
      // The watchdog: a job the engine never came back for is declared dead
      // the first time anyone looks at it, instead of spinning forever.
      const dead = staleJob(job, Date.now());
      if (dead) {
        job = dead;
        await writeJob(env, job);
      }

      if (tail === '/callback' && request.method === 'POST') return handleCallback(request, env, job);

      const engine = secretMatches(request.headers.get('x-scheinman-engine'), env.ENGINE_SECRET);
      // The archive outlives the visitor's link: the owner reads a closed job,
      // and so does the engine that is still working on it.
      const owner = engine || (await isOwner(request, env));
      if (!owner && linkExpired(job, Date.now())) {
        return fail(
          `This link closed on ${job.public_until.slice(0, 10)}. The report is kept in the archive.`,
          410,
        );
      }
      if (!tail && request.method === 'GET') return json(publicView(job));
      if (tail === '/part' && request.method === 'GET') {
        if (!engine) return fail('not authorised', 401);
        const bytes = await env.JOBS.get(blobKey(id, 'submitted_step'), 'arrayBuffer');
        return bytes ? new Response(bytes, { headers: { 'content-type': 'model/step' } }) : fail('gone', 404);
      }
      const fileRoute = tail?.match(/^\/files\/([a-z_]+)$/);
      if (fileRoute && request.method === 'GET') return handleFile(env, job, fileRoute[1]);
      return fail('not found', 404);
    }

    if (path.startsWith('/api/')) return fail('not found', 404);

    // The site's pages. The map lives in logic.mjs because the builder depends
    // on it too: a page written but not routed is a page nobody can open.
    if (path in PAGES) return page(request, env, url, PAGES[path]);
    // The addresses version 2 answered while both versions were up. A link
    // someone already sent still opens the page it promised (2026-09-11).
    const moved = movedFrom(path, base);
    if (moved) {
      return new Response(null, {
        status: 301,
        headers: { ...SECURITY_HEADERS, location: moved, 'cache-control': 'no-store' },
      });
    }
    if (path.startsWith('/samples/')) {
      // The asset lives at its own path inside the build, never at the public
      // one, so a prefixed request is looked up without the prefix.
      const asset = await env.ASSETS.fetch(new Request(new URL(path, url), request));
      return new Response(asset.body, { status: asset.status, headers: { ...Object.fromEntries(asset.headers), ...SECURITY_HEADERS } });
    }
    // Anything else: the dashboard, which is the map of what does exist, with
    // an honest 404 so a machine is not told the address was fine.
    return page(request, env, url, 'home', 404);
}
