// Tiger Data (TimescaleDB) access for the Python Worker. Python Workers have no TCP sockets for a Postgres driver,
// so this Worker owns the database: node-postgres through Hyperdrive, exposed only as RPC over a service binding.
import { WorkerEntrypoint } from 'cloudflare:workers'
import { Client } from 'pg'

type Env = { HYPERDRIVE: Hyperdrive }

export type Reading = { entity_id: string; domain: string; metric: string; value: number; unit?: string | null; source?: string | null; ts: number }
export type DonkiEvent = { id: string; type: string; time: number; data: unknown }

const SCHEMA = `
CREATE TABLE IF NOT EXISTS indicators (
  time timestamptz NOT NULL,
  entity_id text NOT NULL,
  domain text NOT NULL,
  metric text NOT NULL,
  value double precision NOT NULL,
  unit text,
  source text
);
SELECT create_hypertable('indicators', by_range('time'), if_not_exists => TRUE);
-- A queue retry delivers the same readings again: the key makes the second insert a no-op.
CREATE UNIQUE INDEX IF NOT EXISTS indicators_key ON indicators (entity_id, domain, metric, time);
CREATE TABLE IF NOT EXISTS donki_events (
  id text PRIMARY KEY,
  type text NOT NULL,
  time timestamptz NOT NULL,
  data jsonb NOT NULL
);
`

let schemaReady = false // once per isolate; every statement above is idempotent

export class Tiger extends WorkerEntrypoint<Env> {
	private async db<T>(fn: (c: Client) => Promise<T>): Promise<T> {
		// Hyperdrive pools the real connections, so a client per call is cheap.
		const c = new Client({ connectionString: this.env.HYPERDRIVE.connectionString })
		await c.connect()
		try {
			if (!schemaReady) {
				await c.query(SCHEMA)
				schemaReady = true
			}
			return await fn(c)
		} finally {
			await c.end()
		}
	}

	/** One INSERT for the whole batch, as column arrays. Returns how many rows were new. */
	async insertIndicators(rows: Reading[]): Promise<number> {
		const ok = rows.filter((r) => Number.isFinite(r.value) && Number.isFinite(r.ts))
		if (!ok.length) return 0
		return this.db(async (c) => {
			const res = await c.query(
				`INSERT INTO indicators (time, entity_id, domain, metric, value, unit, source)
				 SELECT to_timestamp(t / 1000.0), e, d, m, v, u, s
				 FROM unnest($1::float8[], $2::text[], $3::text[], $4::text[], $5::float8[], $6::text[], $7::text[]) AS x(t, e, d, m, v, u, s)
				 ON CONFLICT DO NOTHING`,
				[
					ok.map((r) => r.ts),
					ok.map((r) => r.entity_id),
					ok.map((r) => r.domain),
					ok.map((r) => r.metric),
					ok.map((r) => r.value),
					ok.map((r) => r.unit ?? null),
					ok.map((r) => r.source ?? null),
				],
			)
			return res.rowCount ?? 0
		})
	}

	async insertDonki(events: DonkiEvent[]): Promise<number> {
		const ok = events.filter((e) => e.id && Number.isFinite(e.time))
		if (!ok.length) return 0
		return this.db(async (c) => {
			const res = await c.query(
				`INSERT INTO donki_events (id, type, time, data)
				 SELECT i, ty, to_timestamp(t / 1000.0), dt FROM unnest($1::text[], $2::text[], $3::float8[], $4::jsonb[]) AS x(i, ty, t, dt)
				 ON CONFLICT (id) DO UPDATE SET type = excluded.type, time = excluded.time, data = excluded.data`,
				[ok.map((e) => e.id), ok.map((e) => e.type), ok.map((e) => e.time), ok.map((e) => JSON.stringify(e.data))],
			)
			return res.rowCount ?? 0
		})
	}

	/**
	 * Daily averages per indicator over the last `days` days of this crew member's record. The window ends at their
	 * newest reading (mission time), not the wall clock, so a replayed mission has history too.
	 */
	async history(entityId: string, days: number) {
		return this.db(async (c) => {
			const res = await c.query(
				`WITH last AS (SELECT max(time) AS t FROM indicators WHERE entity_id = $1)
				 SELECT (extract(epoch FROM time_bucket('1 day', i.time)) * 1000)::float8 AS day, i.domain, i.metric,
				        avg(i.value)::float8 AS avg, count(*)::int AS n
				 FROM indicators i, last
				 WHERE i.entity_id = $1 AND i.time > last.t - make_interval(days => $2::int)
				 GROUP BY 1, 2, 3 ORDER BY 1`,
				[entityId, days],
			)
			return res.rows as { day: number; domain: string; metric: string; avg: number; n: number }[]
		})
	}

	/** Demo only: forget these crew members' readings, so a new run learns its baselines again. */
	async wipe(entityIds: string[]): Promise<number> {
		return this.db(async (c) => (await c.query('DELETE FROM indicators WHERE entity_id = ANY($1::text[])', [entityIds])).rowCount ?? 0)
	}
}

// No public routes: workers_dev is off and the Python Worker reaches Tiger only through the service binding.
export default {
	fetch: () => new Response('not found', { status: 404 }),
}
