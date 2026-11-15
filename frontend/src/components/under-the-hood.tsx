import { useEffect, useState } from 'react'
import { short } from '@/lib/ledger'
import { clock, humanize } from '@/lib/playbook'

type Hood = {
  durable_objects: { name: string; crew_sockets?: number; earth_sockets?: number; outbox?: number; next_alarm?: number | null }[]
  queue: { name: string; sent: number; done: number; backlog: number }
  ai_last: { model: string; ms: number; ok: boolean; at: number; gateway: string; log_id: string | null } | null
  ledger_head: { seq: number; hash: string; pending: number; chain: string } | null
  workflows: { id: string; entity_id: string; message: string; stage: string; status: string }[]
  now: number
}

const secs = (ms: number) => `${Math.max(0, Math.round(ms / 1000))} s`

/** Live Cloudflare internals, polled every 5 seconds. Every number comes from the Worker, none is computed here. */
export function UnderTheHood() {
  const [hood, setHood] = useState<Hood | null>(null)
  const [failed, setFailed] = useState(false)

  useEffect(() => {
    let stopped = false
    const load = async () => {
      try {
        const res = await fetch('/api/hood')
        if (!res.ok) throw new Error(String(res.status))
        const body = await res.json()
        if (!stopped) {
          setHood(body)
          setFailed(false)
        }
      } catch {
        if (!stopped) setFailed(true)
      }
    }
    load()
    const timer = window.setInterval(load, 5000)
    return () => {
      stopped = true
      window.clearInterval(timer)
    }
  }, [])

  return (
    <details className="sec">
      <summary className="flex min-h-11 items-center justify-between gap-3">
        <h2 className="sec-title">Under the hood</h2>
        <span className="chevron" />
      </summary>
      {failed && <p className="mt-2 text-warn">The panel did not load. Trying again every 5 seconds.</p>}
      {hood && (
        <dl className="mt-3 grid gap-x-8 gap-y-4 text-sm @xl:grid-cols-2">
          <div>
            <dt className="label">Durable Objects</dt>
            <dd>
              <ul>
                {hood.durable_objects.map((d) => (
                  <li key={d.name}>
                    <span className="font-bold">{humanize(d.name)}</span>
                    {d.outbox !== undefined && (
                      <span className="text-muted-foreground">
                        {' '}
                        · {d.crew_sockets} crew, {d.earth_sockets} Earth sockets · {d.outbox} on the way to Earth
                        {d.next_alarm ? ` · alarm in ${secs(d.next_alarm - hood.now)}` : ''}
                      </span>
                    )}
                  </li>
                ))}
              </ul>
            </dd>
          </div>
          <div>
            <dt className="label">Queue {hood.queue.name}</dt>
            <dd>
              <span className="font-bold">{hood.queue.backlog} waiting</span>{' '}
              <span className="text-muted-foreground">
                ({hood.queue.sent} sent, {hood.queue.done} consumed)
              </span>
            </dd>
          </div>
          <div>
            <dt className="label">Last Workers AI call, via AI Gateway</dt>
            <dd>
              {hood.ai_last ? (
                <>
                  <span className="font-bold">{hood.ai_last.ms} ms</span> {hood.ai_last.model}
                  <span className="block text-muted-foreground">
                    {hood.ai_last.ok ? 'Answered' : 'Failed'} at {clock.format(hood.ai_last.at)} UTC through gateway{' '}
                    {hood.ai_last.gateway}
                    {hood.ai_last.log_id ? `, log ${hood.ai_last.log_id}` : ''}
                  </span>
                </>
              ) : (
                'No call yet.'
              )}
            </dd>
          </div>
          <div>
            <dt className="label">Ledger head, R2 locked under ledger/</dt>
            <dd>
              {hood.ledger_head ? (
                <>
                  <span className="font-bold">
                    #{hood.ledger_head.seq} {short(hood.ledger_head.hash)}
                  </span>
                  {hood.ledger_head.pending > 0 && (
                    <span className="text-muted-foreground"> · {hood.ledger_head.pending} not copied yet</span>
                  )}
                </>
              ) : (
                'Empty.'
              )}
            </dd>
          </div>
          <div className="@xl:col-span-2">
            <dt className="label">Running Workflows</dt>
            <dd>
              {hood.workflows.length === 0
                ? 'None.'
                : hood.workflows.map((w) => (
                    <p key={w.id}>
                      <span className="font-bold">{humanize(w.entity_id)}</span> {w.message}{' '}
                      <span className="text-muted-foreground">
                        · {w.status}, step {w.stage}
                      </span>
                    </p>
                  ))}
            </dd>
          </div>
        </dl>
      )}
    </details>
  )
}
