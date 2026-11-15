import { useEffect, useState } from 'react'
import { humanize, type Playbook } from '@/lib/playbook'

type Series = { domain: string; metric: string; points: [number, number][] } // [day ms, daily average]
type History = { days: number; series: Series[]; chronic: Record<string, { per_day: number; days: number }> }

const RANGES = [30, 90, 180] as const
const number = new Intl.NumberFormat('en', { maximumFractionDigits: 2 })
const day = new Intl.DateTimeFormat('en-GB', { day: 'numeric', month: 'short', timeZone: 'UTC' })
const segment =
  '-ml-px min-h-11 border border-input px-3 text-sm first:ml-0 aria-pressed:z-10 aria-pressed:border-primary aria-pressed:bg-primary aria-pressed:font-bold aria-pressed:text-primary-foreground'

/** One indicator's daily averages: its own vertical scale, the shared time axis of the range. */
function Line({ s, from, to, label, unit, perDay }: { s: Series; from: number; to: number; label: string; unit?: string | null; perDay?: number }) {
  const vs = s.points.map((p) => p[1])
  const lo = Math.min(...vs)
  const hi = Math.max(...vs)
  const pad = (hi - lo || Math.abs(hi) || 1) * 0.15
  const x = (t: number) => ((t - from) / (to - from || 1)) * 100
  const y = (v: number) => 100 - ((v - (lo - pad)) / (hi - lo + 2 * pad)) * 100
  const last = s.points.at(-1)!
  const trend =
    perDay === undefined ? '' : ` Trend ${perDay >= 0 ? '+' : ''}${number.format(perDay * 7)}${unit ? ` ${unit}` : ''} a week.`
  return (
    <div className="mt-3">
      <p className="text-sm">
        <span className="font-bold">{label}</span>{' '}
        <span className="text-muted-foreground">
          {number.format(last[1])}
          {unit ? ` ${unit}` : ''} on {day.format(last[0])}, range {number.format(lo)} to {number.format(hi)}.{trend}
        </span>
      </p>
      <svg aria-hidden viewBox="0 0 100 100" preserveAspectRatio="none" className="mt-1 h-12 w-full overflow-visible">
        <polyline
          points={s.points.map(([t, v]) => `${x(t)},${y(v)}`).join(' ')}
          fill="none"
          stroke="var(--signal)"
          strokeWidth="2"
          strokeLinejoin="round"
          vectorEffect="non-scaling-stroke"
        />
        {s.points.length === 1 && <circle cx={x(last[0])} cy={y(last[1])} r="2" fill="var(--signal)" />}
      </svg>
    </div>
  )
}

/** Long-term history from Tiger Data: daily averages per domain over 30, 90 or 180 days of this crew member's record. */
export function TrendCharts({ entityId, playbook }: { entityId: string; playbook: Playbook | null }) {
  const [days, setDays] = useState<(typeof RANGES)[number]>(30)
  const [history, setHistory] = useState<History | null>(null)
  const [failed, setFailed] = useState(false)

  useEffect(() => {
    let stopped = false
    const load = async () => {
      try {
        const res = await fetch(`/api/astronauts/${encodeURIComponent(entityId)}/history?days=${days}`)
        if (!res.ok) throw new Error(String(res.status))
        const body = await res.json()
        if (!stopped) {
          setHistory(body)
          setFailed(false)
        }
      } catch {
        if (!stopped) setFailed(true)
      }
    }
    load()
    const timer = window.setInterval(load, 60_000)
    return () => {
      stopped = true
      window.clearInterval(timer)
    }
  }, [entityId, days])

  const byDomain = new Map<string, Series[]>()
  for (const s of history?.series ?? []) byDomain.set(s.domain, [...(byDomain.get(s.domain) ?? []), s])
  const all = history?.series.flatMap((s) => s.points.map((p) => p[0])) ?? []
  const to = all.length ? Math.max(...all) : 0
  const from = to - (days - 1) * 86_400_000

  return (
    <section aria-labelledby="history" className="mt-12">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h2 id="history" className="sec-title">
            Your long-term trends
          </h2>
          <p className="mt-1 text-sm text-muted-foreground">Daily averages, kept in Tiger Data.</p>
        </div>
        <div role="group" aria-label="Time range" className="flex">
          {RANGES.map((r) => (
            <button key={r} type="button" className={segment} aria-pressed={days === r} onClick={() => setDays(r)}>
              {r} days
            </button>
          ))}
        </div>
      </div>
      {failed && <p className="mt-3 text-warn">History did not load. Trying again every minute.</p>}
      {history && byDomain.size === 0 && <p className="mt-3">No history yet.</p>}
      <div className="mt-4 grid gap-6 @xl:grid-cols-2 @4xl:grid-cols-3">
        {[...byDomain].map(([domain, series]) => (
          <figure key={domain} className="border-t pt-4">
            <figcaption className="font-bold">{playbook?.domains[domain]?.label ?? humanize(domain)}</figcaption>
            {series.map((s) => {
              const spec = playbook?.domains[domain]?.indicators[s.metric]
              return (
                <Line
                  key={s.metric}
                  s={s}
                  from={from}
                  to={to}
                  label={spec?.label ?? humanize(s.metric)}
                  unit={spec?.unit}
                  perDay={history?.chronic[`${domain}/${s.metric}`]?.per_day}
                />
              )
            })}
          </figure>
        ))}
      </div>
    </section>
  )
}
