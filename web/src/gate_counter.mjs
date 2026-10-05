// The door's attempt counter, in one place per visitor and hour.
//
// It lived in KV first: read the count, compare, write count + 1. KV is
// eventually consistent and that sequence is not atomic, so ten guesses sent
// at once could all read "0" and all be allowed (audit 2026-09-02). A
// Durable Object runs its requests one at a time, so the count it returns is
// the count that was written. The object forgets itself two hours later.

const TWO_HOURS = 2 * 60 * 60 * 1000;

export class GateCounter {
  constructor(state) {
    this.state = state;
  }

  async fetch(request) {
    const count = (await this.state.storage.get('count')) ?? 0;
    if (request.method === 'GET') {
      return new Response(JSON.stringify({ count }), { headers: { 'content-type': 'application/json' } });
    }
    if (request.method === 'POST' && new URL(request.url).pathname === '/reset') {
      await this.state.storage.put('count', 0);
      return new Response(JSON.stringify({ count: 0 }), { headers: { 'content-type': 'application/json' } });
    }
    if (request.method === 'POST') {
      const next = count + 1;
      await this.state.storage.put('count', next);
      if ((await this.state.storage.getAlarm()) === null) {
        await this.state.storage.setAlarm(Date.now() + TWO_HOURS);
      }
      return new Response(JSON.stringify({ count: next }), { headers: { 'content-type': 'application/json' } });
    }
    return new Response('{"error":"not found"}', { status: 404 });
  }

  async alarm() {
    await this.state.storage.deleteAll();
  }
}
