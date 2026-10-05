// The counter's rules, as pure functions. Nothing here touches the network or
// storage, so every rule is tested directly with `node --test` and the request
// handler stays thin enough to read in one sitting.

// A submitted part is capped well below the KV value limit; the engine runs in
// seconds on plates this size and a bigger file is not a plate.
export const MAX_UPLOAD_BYTES = 10 * 1024 * 1024;
// The same number as people read it. Every sentence that names the cap builds
// it from here, and a test pins the page's own wording to it (audit 2026-09-02).
export const MAX_UPLOAD_MB = MAX_UPLOAD_BYTES / 1024 / 1024;
// Every STEP file starts with this token (ISO 10303-21). Checking the bytes,
// not the extension, is what stops a renamed archive from reaching the engine.
export const STEP_MAGIC = 'ISO-10303-21';
export const ALLOWED_EXTENSIONS = ['.step', '.stp'];
// The declarations. Both closed vocabularies, owned by the engine
// (scheinman.schemas.MATERIAL_SERIES and Loading); a value outside them is
// refused here so it never reaches a workflow run. The wrought aluminum series
// stop at 8xxx: 9xxx is reserved and names no alloy (ecosystem/CONTRACTS.md).
export const MATERIAL_SERIES = ['1xxx', '2xxx', '3xxx', '4xxx', '5xxx', '6xxx', '7xxx', '8xxx'];
export const LOADINGS = ['cyclic', 'static'];
// One visitor, one day. Generous for a real engineer, useless for a robot.
export const DAILY_LIMIT = 5;
// Every visitor together, one day: the engine runs on free minutes, and a
// crowd of honest visitors must not spend them all (audit 2026-09-02).
export const GLOBAL_DAILY_LIMIT = 50;
// How long the visitor's own link keeps working. Nothing is deleted when it
// closes: the owner's archive keeps every finished job (decision 2026-09-01).
export const PUBLIC_WINDOW_DAYS = 30;

const SAFE_NAME = /^[A-Za-z0-9][A-Za-z0-9._-]{0,59}$/;

/** The part name the engine will use, or null when the filename is not one. */
export function partNameFrom(filename) {
  const lower = String(filename || '').toLowerCase();
  const extension = ALLOWED_EXTENSIONS.find((e) => lower.endsWith(e));
  if (!extension) return null;
  const stem = String(filename).slice(0, -extension.length);
  return SAFE_NAME.test(stem) ? stem : null;
}

/** Why this upload cannot be accepted, or null when it can. */
export function uploadRefusal({ filename, bytes, materialSeries, loading }) {
  if (!bytes || bytes.byteLength === 0) return 'The file is empty.';
  if (bytes.byteLength > MAX_UPLOAD_BYTES) {
    return `The file is ${(bytes.byteLength / 1024 / 1024).toFixed(1)} MB. The counter takes up to ${MAX_UPLOAD_MB} MB.`;
  }
  if (!partNameFrom(filename)) {
    return 'The file must be a .step or .stp file, named with letters, digits, dot, dash or underscore.';
  }
  const head = new TextDecoder('latin1').decode(bytes.slice(0, 200));
  if (!head.includes(STEP_MAGIC)) {
    return 'This file does not carry a STEP header, so it is not the CAD file the engine reads.';
  }
  if (!MATERIAL_SERIES.includes(materialSeries)) return 'Declare the alloy series of the material.';
  if (!LOADINGS.includes(loading)) return 'Declare whether the part is cyclically or statically loaded.';
  return null;
}

/** Unguessable job id: the id IS the capability to read the job. */
export function newJobId(randomBytes) {
  return Array.from(randomBytes, (b) => b.toString(16).padStart(2, '0')).join('');
}

export const jobKey = (id) => `job:${id}`;
export const blobKey = (id, role) => `blob:${id}:${role}`;
export const rateKey = (visitor, day) => `rate:${visitor}:${day}`;
/** The archive's index. Keys sort by time, so listing them and reversing gives
 * newest first without holding every job in memory. */
export const indexKey = (job) => `index:${job.created_at}:${job.id}`;

/** One line of the owner's archive: enough to find a job, never the whole record. */
export function indexEntry(job) {
  return {
    id: job.id,
    part_name: job.part_name,
    status: job.status,
    material_series: job.material_series,
    loading: job.loading,
    created_at: job.created_at,
    public_until: job.public_until,
    findings: job.result?.violations?.length ?? 0,
  };
}

/** UTC day stamp, the unit the daily limit counts in. */
export function dayStamp(now) {
  return new Date(now).toISOString().slice(0, 10);
}

export function rateRefusal(countSoFar, limit = DAILY_LIMIT) {
  if (countSoFar < limit) return null;
  return `This counter runs ${limit} parts per visitor per day, and today's ${limit} are used. It resets at midnight UTC.`;
}

export const globalRateKey = (day) => `rate:global:${day}`;

export function globalRefusal(countSoFar, limit = GLOBAL_DAILY_LIMIT) {
  if (countSoFar < limit) return null;
  return `The counter ran its ${limit} parts for today, for everyone together. It reopens at midnight UTC.`;
}

/** What to do about the human check, given how the counter is configured.
 * Without its secret the check used to pass everyone in silence (audit
 * 2026-09-02). Now: verify when configured; on a machine that says so
 * explicitly (local development), skip; anywhere else, close the counter. */
export function humanCheckMode(secret, localDev) {
  if (secret) return 'verify';
  return String(localDev) === 'true' ? 'skip' : 'closed';
}

/** The owner's health line, readable with the engine's key: counts only, no
 * part names, so a workflow log never opens the archive. */
export function healthSummary(entries, now, staleAfterMs = STALE_AFTER_MS, windowMs = 24 * 60 * 60 * 1000) {
  const recent = entries.filter((e) => now - Date.parse(e.created_at) <= windowMs);
  const errors = recent.filter((e) => e.status === 'error').length;
  const stalled = entries.filter(
    (e) => (e.status === 'queued' || e.status === 'running') && now - Date.parse(e.created_at) >= staleAfterMs,
  ).length;
  const last = entries.map((e) => e.created_at).sort().at(-1) ?? null;
  return { jobs_24h: recent.length, errors_24h: errors, stalled, last_job_at: last, healthy: errors === 0 && stalled === 0 };
}

/** How often the alarm may ring while the counter stays unhealthy. Measured
 * 2026-09-03: GitHub's scheduled runs are best effort (4 fired in 10.4 h under
 * an hourly cron, one gap of 10.7 h), so the counter now watches itself on a
 * Cloudflare cron and rings through a GitHub workflow that fails. Ringing every
 * half hour would bury the owner, so one ring per this window. */
export const ALERT_EVERY_MS = 6 * 60 * 60 * 1000;

/** Where the last ring is remembered, so the alarm does not repeat every tick. */
export const ALERT_KEY = 'alert:last';

/** Decide whether this tick should ring. Pure: the caller does the I/O.
 * `lastAlertAt` is the ISO time of the last ring, or null if it never rang. */
export function shouldAlert(summary, lastAlertAt, now, everyMs = ALERT_EVERY_MS) {
  if (summary.healthy) return { ring: false, reason: '' };
  const since = lastAlertAt ? now - Date.parse(lastAlertAt) : Infinity;
  if (Number.isFinite(since) && since < everyMs) return { ring: false, reason: '' };
  const parts = [];
  if (summary.errors_24h > 0) parts.push(`${summary.errors_24h} job(s) died in the last 24 h`);
  if (summary.stalled > 0) parts.push(`${summary.stalled} job(s) stalled with no answer from the engine`);
  return { ring: true, reason: `SCHEINMAN: ${parts.join('; ')}` };
}

/** When the visitor's link closes. The job itself is kept beyond it. */
export function publicUntil(now, days = PUBLIC_WINDOW_DAYS) {
  return new Date(now + days * 24 * 60 * 60 * 1000).toISOString();
}

export function linkExpired(job, now) {
  return Boolean(job.public_until) && new Date(job.public_until).getTime() < now;
}

/** A visitor identifier that is not a stored IP address: same visitor, same
 * day, same bucket, and nothing personal kept once the day rolls over. */
export async function visitorBucket(ip, day, subtle = crypto.subtle) {
  const data = new TextEncoder().encode(`${ip}|${day}`);
  const digest = await subtle.digest('SHA-256', data);
  return Array.from(new Uint8Array(digest).slice(0, 8), (b) => b.toString(16).padStart(2, '0')).join('');
}

/** The record a job starts life as. The status vocabulary beyond these two is
 * the engine's (ecosystem/CONTRACTS.md); the counter never invents one. */
export function newJob({ id, partName, materialSeries, loading, now }) {
  return {
    id,
    status: 'queued',
    part_name: partName,
    material_series: materialSeries,
    loading,
    created_at: new Date(now).toISOString(),
    public_until: publicUntil(now),
    result: null,
    reason: null,
  };
}

/** What the visitor's page is allowed to see. Never the whole record: the
 * engine's callback secret and internal fields stay on this side. */
export function publicView(job) {
  return {
    id: job.id,
    status: job.status,
    part_name: job.part_name,
    material_series: job.material_series,
    loading: job.loading,
    created_at: job.created_at,
    public_until: job.public_until,
    started_at: job.started_at ?? null,
    finished_at: job.finished_at ?? null,
    reason: job.reason ?? null,
    result: job.result ?? null,
    files: job.result ? Object.keys(job.result.files ?? {}) : [],
  };
}

/** Progress only moves forward: a late "queued" can never demote a finished
 * job, and only the engine's terminal statuses end it. */
// The counter's own statuses (queued, running, error) plus the engine's four
// (ecosystem/CONTRACTS.md: "job status" and "counter states").
export const RANK = { queued: 0, running: 1, clean: 2, corrected: 2, uncorrected: 2, refused: 2, error: 2 };

export function canAdvance(from, to) {
  if (!(to in RANK)) return false;
  return RANK[to] > RANK[from];
}

/** The watchdog. The engine's run is capped at 15 minutes and a failed run
 * reports itself, but a runner that never starts, or dies before it can speak,
 * reports nothing, and a page would spin forever (audit 2026-09-02).
 * A job still queued or running this long after it was created is declared
 * dead at read time, honestly: nothing was measured, nothing was delivered. */
export const STALE_AFTER_MS = 30 * 60 * 1000;

export function staleJob(job, now) {
  if (job.status !== 'queued' && job.status !== 'running') return null;
  if (now - Date.parse(job.created_at) < STALE_AFTER_MS) return null;
  return {
    ...job,
    status: 'error',
    watchdog: true,
    finished_at: new Date(now).toISOString(),
    reason: 'The engine did not report back within 30 minutes. Nothing was measured and nothing was delivered; if the run finishes later its delivery still lands here. The owner can find the run in the engine log.',
  };
}

/** A delivery that arrives after the watchdog gave up is still the truth about
 * the part: it replaces the watchdog's verdict, and only the watchdog's. A job
 * the engine itself ended never moves again (audit 2026-09-02). */
export function acceptsLateDelivery(job, status) {
  return job.status === 'error' && job.watchdog === true && status in RANK && RANK[status] === 2 && status !== 'error';
}

/** The archive lists newest first. The index keys sort by creation time, so
 * the newest are the LAST keys, and a listing capped at N would keep the
 * oldest N (audit 2026-09-02). Take the tail, then reverse. */
export function newestFirst(entries, limit) {
  const sorted = [...entries].sort((a, b) => (a.created_at < b.created_at ? -1 : a.created_at > b.created_at ? 1 : 0));
  return sorted.slice(Math.max(0, sorted.length - limit)).reverse();
}

/* ---------------------------------------------------------------------------
 * The door in front of everything (owner's decision, 2026-09-01).
 *
 * The site is not public yet: one password opens it, and what the browser
 * keeps afterwards is a signed ticket with an expiry, never the password.
 * Changing the password invalidates every ticket, because the password is the
 * signing key.
 * ------------------------------------------------------------------------- */

export const GATE_COOKIE = 'scheinman_gate';
/* How long a ticket lives with nobody using it. It was seven days until
 * 2026-09-11, when the owner opened the site, was let straight in, and read
 * that as a site with no door ("it must always ask for the password, ALWAYS"). It
 * became half an hour, counted from the moment the password was typed, which
 * put the door in front of a reader who was still reading.
 *
 * Since 2026-09-20 it is idle time, not total time: every request that arrives
 * with a live ticket is answered with a fresh one, so navigating never meets
 * the door. Fifteen minutes, because that is now the only thing standing
 * between a closed browser and the site: see SESSION_MAX_HOURS below.
 * A running job is unaffected: the engine carries its own key, and the work
 * continues whether or not anyone is watching the page. */
export const SESSION_HOURS = 0.25;
/* And a ceiling the sliding window cannot push: a ticket dies two hours after
 * the password was typed, however much the site is used in between.
 *
 * Why both, 2026-09-20: the owner closed the browser, opened it again and was
 * let straight in. The cookie is a session cookie and always was, but a browser
 * set to "continue where you left off" restores session cookies on restart, so
 * "the browser closed" is not something this Worker can ever observe. Time is.
 * Fifteen minutes of not touching the site, or two hours in total, and the
 * password is asked for again. */
export const SESSION_MAX_HOURS = 2;
// A person mistypes a password a few times; a robot tries thousands.
export const GATE_ATTEMPTS_PER_HOUR = 10;

export const gateAttemptKey = (visitor, hour) => `gate:${visitor}:${hour}`;
export const hourStamp = (now) => new Date(now).toISOString().slice(0, 13);

/** When a lockout lifts: the attempt counter is keyed by the UTC hour, so it
 * resets at the next hour boundary, not "an hour from now". The owner locked
 * himself out once and was told to wait an hour; the truth was nine minutes. */
export function lockoutLifts(now) {
  const next = new Date(now);
  next.setUTCMinutes(0, 0, 0);
  next.setUTCHours(next.getUTCHours() + 1);
  return next;
}

/** The sentence the door says to a wrong password: honest about what is left,
 * so a person who mistypes knows where they stand before the lock closes. */
export function wrongPasswordMessage(tried, now, limit = GATE_ATTEMPTS_PER_HOUR) {
  const left = Math.max(0, limit - tried);
  if (left === 0) {
    return `That password does not open this site. No attempts left this hour; the door reopens at ${lockoutLifts(now).toISOString().slice(11, 16)} UTC.`;
  }
  return (
    'That password does not open this site. ' +
    `${left} ${left === 1 ? 'attempt' : 'attempts'} left this hour. ` +
    'If your browser filled the field, clear it and type the password yourself.'
  );
}

export function lockedMessage(now) {
  const lifts = lockoutLifts(now);
  return `Too many attempts. The door reopens at ${lifts.toISOString().slice(11, 16)} UTC.`;
}

/** Compare two secrets without leaking, in the timing, how much matched. */
export function secretMatches(given, expected) {
  if (typeof given !== 'string' || typeof expected !== 'string' || !expected) return false;
  const a = new TextEncoder().encode(given);
  const b = new TextEncoder().encode(expected);
  if (a.length !== b.length) return false;
  let diff = 0;
  for (let i = 0; i < a.length; i += 1) diff |= a[i] ^ b[i];
  return diff === 0;
}

/** The signing key is the password AND a random secret the Worker holds
 * (TICKET_KEY). Changing the password still kills every ticket, which was the
 * design; and a stolen ticket no longer lets anyone test password guesses
 * offline against a known signature (audit 2026-09-02). */
async function sign(value, password, subtle, pepper = '') {
  const key = await subtle.importKey(
    'raw',
    new TextEncoder().encode(`${pepper}|${password}`),
    { name: 'HMAC', hash: 'SHA-256' },
    false,
    ['sign'],
  );
  const mac = await subtle.sign('HMAC', key, new TextEncoder().encode(value));
  return Array.from(new Uint8Array(mac), (b) => b.toString(16).padStart(2, '0')).join('');
}

/** The ticket the browser keeps: when it goes idle, when it was born, and
 * proof we issued it. Both times are signed together, so neither can be moved
 * without the other and neither can be moved at all. */
export async function newTicket(
  password,
  now,
  subtle = crypto.subtle,
  hours = SESSION_HOURS,
  pepper = '',
  born = now,
) {
  const expires = String(now + hours * 60 * 60 * 1000);
  const start = String(born);
  return `${expires}.${start}.${await sign(`${expires}|${start}`, password, subtle, pepper)}`;
}

/** When the ticket in hand was first issued, so renewing it does not restart
 * the ceiling. Null when there is nothing readable to carry forward. */
export function ticketBorn(ticket) {
  const [, born] = String(ticket ?? '').split('.');
  return /^\d+$/.test(born ?? '') ? Number(born) : null;
}

export async function ticketValid(
  ticket,
  password,
  now,
  subtle = crypto.subtle,
  pepper = '',
  maxHours = SESSION_MAX_HOURS,
) {
  if (typeof ticket !== 'string') return false;
  const [expires, born, signature] = ticket.split('.');
  if (!expires || !born || !signature) return false;
  if (!/^\d+$/.test(expires) || !/^\d+$/.test(born)) return false;
  if (Number(expires) <= now) return false;
  if (now - Number(born) >= maxHours * 60 * 60 * 1000) return false;
  return secretMatches(signature, await sign(`${expires}|${born}`, password, subtle, pepper));
}

/** What the browser is told after the owner locks the door: the same cookie,
 * emptied and expired. The next page load shows the password again. */
export const lockCookie = (base = '') =>
  `${GATE_COOKIE}=; Path=${cookiePath(base)}; HttpOnly; Secure; SameSite=Lax; Max-Age=0`;

/** A person who was inside and whose ticket died (seven days passed, or the
 * password was rotated) must not be told the site "is not open yet". */
export const SESSION_ENDED = 'Your session ended. Reload the page and enter the password again.';

export function readCookie(header, name) {
  for (const piece of String(header || '').split(';')) {
    const [key, ...rest] = piece.trim().split('=');
    if (key === name) return rest.join('=');
  }
  return null;
}

/** Which requests the door stands in front of: everything except the door.
 *
 * Who gets through is decided by the KEY the request carries, never by which
 * address it asked for. The first version listed the engine's two routes as
 * exceptions and forgot a third, so the engine reached the site, read nothing,
 * and every job died at 401 (live run 33524550342, 2026-09-01). A list of
 * exceptions is a list waiting to be incomplete. */
/** The site's addresses. One owner, because two parts depend on it: the builder
 * writes a file per page and the router answers a path per page. The guided
 * conference was built and unreachable for one deploy because the router had a
 * list of four (2026-09-03, lesson 023); web/test/worker.test.mjs now binds the
 * two together.
 *
 * For one week two skins served the same product, version 1 on these addresses
 * and version 2 under /v2. The owner chose version 2 on 2026-09-11, so there is
 * one site again and it answers here. */
export const PAGES = {
  '/': 'home',
  '/inspect': 'inspect',
  '/archive': 'archive',
  '/evidence': 'evidence',
};

/* --- The base path -------------------------------------------------------
 *
 * The site was written assuming it owns the root of a hostname, which it does
 * at scheinman.example.com. Central hosting wants to mount the same app under
 * a prefix on a shared site (shared-host mounting, 2026-09-15), so every address it
 * emits and answers has to carry that prefix, natively, not through a proxy
 * that rewrites content on the way out.
 *
 * The default is "" and means the root, so the deployment that is live today
 * behaves exactly as it did. Nothing below changes unless a base path is set.
 */

/** A base path in one shape: "" for the root, or "/a/b" with no trailing slash.
 * Anything unusable (not a string, "/", only slashes) reads as the root, so a
 * misconfigured value cannot silently produce addresses like "//inspect". */
export function normalizeBase(value) {
  if (typeof value !== 'string') return '';
  const trimmed = value.trim();
  if (!trimmed || trimmed === '/') return '';
  const withSlash = trimmed.startsWith('/') ? trimmed : `/${trimmed}`;
  const clean = withSlash.replace(/\/+$/, '').replace(/\/{2,}/g, '/');
  return clean === '/' ? '' : clean;
}

/** An address of this site, as the browser should see it. */
export function withBase(base, path) {
  const root = normalizeBase(base);
  if (!root) return path;
  return path === '/' ? root : `${root}${path}`;
}

/** The path with the base taken off, or null when the request is not ours.
 * Everything that routes goes through here, so a request to a neighbour's
 * address on a shared origin is never mistaken for one of ours. */
export function withoutBase(base, path) {
  const root = normalizeBase(base);
  if (!root) return path;
  if (path === root) return '/';
  return path.startsWith(`${root}/`) ? path.slice(root.length) : null;
}

/** Where version 2 used to live. Its addresses were shared while both versions
 * were up, so they are answered with a permanent redirect to the same page at
 * its address today, instead of a 404 that would make a working link look like
 * a broken product. */
export const RETIRED_PREFIX = '/v2';

/** The address that replaces a retired one, or null when there is none.
 * Takes the path already stripped of the base, and answers with a full address
 * the browser can follow. */
export function movedFrom(path, base = '') {
  if (path !== RETIRED_PREFIX && !String(path).startsWith(`${RETIRED_PREFIX}/`)) return null;
  const now = path === RETIRED_PREFIX ? '/' : path.slice(RETIRED_PREFIX.length);
  return now in PAGES ? withBase(base, now) : null;
}

export function needsGate(path) {
  return path !== '/api/gate';
}

/** What the door's cookie is scoped to. On a hostname of our own that is the
 * whole site; under a prefix on a shared site it must be the prefix, or the
 * ticket would be sent to every neighbour on that hostname (shared-host mounting). */
export function cookiePath(base) {
  return normalizeBase(base) || '/';
}

/** The daily cap protects a free engine from strangers. The owner, who is the
 * only person past the door while the site is private, is not a stranger
 * (audit 2026-09-02): a demo of six parts must not stop at the sixth. */
export function countsAgainstDailyLimit(isOwner) {
  return !isOwner;
}
