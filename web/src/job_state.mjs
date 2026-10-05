// One job's state, in one place, always current.
//
// The first live run found the reason this exists: with the job record in KV,
// the page kept saying "queued" for up to a minute after the engine had already
// finished, because a KV read is served from the edge cache of whichever colo
// asked, and the engine's write lands somewhere else. A visitor watching a
// finished job spin is the one moment the product cannot afford to be vague.
//
// A Durable Object is a single addressable place per job: a read after a write
// sees the write. The files themselves stay in KV, where write-once blobs are
// exactly what it is good at.

export class JobState {
  constructor(state) {
    this.state = state;
  }

  async fetch(request) {
    const url = new URL(request.url);
    if (request.method === 'GET') {
      const job = await this.state.storage.get('job');
      return job
        ? new Response(JSON.stringify(job), { headers: { 'content-type': 'application/json' } })
        : new Response('null', { status: 404, headers: { 'content-type': 'application/json' } });
    }
    if (request.method === 'PUT') {
      const job = await request.json();
      await this.state.storage.put('job', job);
      return new Response('{"ok":true}', { headers: { 'content-type': 'application/json' } });
    }
    return new Response('{"error":"not found"}', { status: 404 });
  }
}
