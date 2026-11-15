import { type PointerEvent, useState } from 'react'
import type { Forecast } from '@/hooks/use-live-readings'
import { clock, forecastTime } from '@/lib/playbook'

const number = new Intl.NumberFormat('en', { maximumFractionDigits: 2 })
const DAY = 86_400_000

function span(ms: number) {
  const hours = ms / 3_600_000
  if (hours < 1) return `${Math.round(hours * 60)} minutes`
  if (hours < 48) return `${Math.round(hours)} hours`
  return `${Math.round(hours / 24)} days`
}

type Props = { forecast: Forecast; label: string; unit?: string | null; missionStart?: string }

/** One indicator's digital twin: measured history (solid), where the trend is heading (dashed), and the limit. */
export function ForecastChart({ forecast: f, label, unit, missionStart }: Props) {
  const [hover, setHover] = useState<number | null>(null) // x position, 0..1

  const t0 = f.points[0]?.[0] ?? f.t
  const tEnd = f.eta && f.eta > f.t ? f.eta : f.t + Math.min(f.horizon_ms, Math.max(f.t - t0, 60_000))
  const at = (ts: number) => f.level + f.slope * (ts - f.t) // the twin's value at any time
  const values = [...f.points.map((p) => p[1]), f.threshold, at(tEnd)]
  const lo = Math.min(...values)
  const hi = Math.max(...values)
  const pad = (hi - lo || 1) * 0.1
  const x = (ts: number) => ((ts - t0) / (tEnd - t0 || 1)) * 100
  const y = (v: number) => 100 - ((v - (lo - pad)) / (hi - lo + 2 * pad)) * 100

  const onMove = (e: PointerEvent<HTMLDivElement>) => {
    const box = e.currentTarget.getBoundingClientRect()
    setHover(Math.min(1, Math.max(0, (e.clientX - box.left) / box.width)))
  }
  let readout = ''
  if (hover !== null) {
    const ts = t0 + hover * (tEnd - t0)
    const measured = ts <= f.t && f.points.reduce((a, b) => (Math.abs(b[0] - ts) < Math.abs(a[0] - ts) ? b : a))
    readout = measured
      ? `${clock.format(measured[0])} UTC: ${number.format(measured[1])} ${unit ?? ''} measured`
      : `${clock.format(ts)} UTC: ${number.format(at(ts))} ${unit ?? ''} forecast`
  }

  const limit = `${number.format(f.threshold)}${unit ? ` ${unit}` : ''}`
  const day = f.eta && missionStart ? Math.floor((f.eta - Date.parse(missionStart)) / DAY) + 1 : null
  const sentence = f.eta
    ? f.eta <= f.t
      ? `Now at the ${limit} limit.`
      : `On course to ${f.op === '>=' ? 'reach' : 'fall to'} ${limit} on ${forecastTime(f.eta, f.t)}${day ? ` (mission day ${day})` : ''}.`
    : `Not on course to ${f.op === '>=' ? 'reach' : 'fall to'} ${limit} within the next ${span(f.horizon_ms)}.`

  return (
    <figure className="border-t pt-4">
      <figcaption>
        <span className="font-bold">{label}</span>
        <span className="block text-muted-foreground">{sentence}</span>
        {f.chronic && (
          <span className="block text-muted-foreground">
            Over {f.chronic.days} days of history: {f.chronic.per_day >= 0 ? '+' : ''}
            {number.format(f.chronic.per_day * 7)}
            {unit ? ` ${unit}` : ''} a week.
          </span>
        )}
      </figcaption>
      <div
        className="relative mt-3 h-28 touch-pan-y"
        onPointerMove={onMove}
        onPointerDown={onMove}
        onPointerLeave={() => setHover(null)}
      >
        {/* The sentence above carries the same information for screen readers. */}
        <svg aria-hidden viewBox="0 0 100 100" preserveAspectRatio="none" className="draw-in size-full overflow-visible">
          <line x1="0" x2="100" y1={y(f.threshold)} y2={y(f.threshold)} stroke="var(--warn)" strokeWidth="1" vectorEffect="non-scaling-stroke" />
          <line x1={x(f.t)} x2={x(f.t)} y1="0" y2="100" stroke="var(--border)" strokeWidth="1" vectorEffect="non-scaling-stroke" />
          <polyline
            points={f.points.map(([ts, v]) => `${x(ts)},${y(v)}`).join(' ')}
            fill="none"
            stroke="var(--signal)"
            strokeWidth="2"
            strokeLinejoin="round"
            vectorEffect="non-scaling-stroke"
          />
          <line x1={x(f.t)} y1={y(f.level)} x2="100" y2={y(at(tEnd))} stroke="var(--signal)" strokeWidth="2" strokeDasharray="5 4" vectorEffect="non-scaling-stroke" />
          {hover !== null && <line x1={hover * 100} x2={hover * 100} y1="0" y2="100" stroke="var(--foreground)" strokeWidth="1" vectorEffect="non-scaling-stroke" />}
        </svg>
        {/* Left side: the measured line starts far from the limit there, the forecast ends on it at the right. */}
        <span className="absolute left-0 -translate-y-full text-sm text-warn" style={{ top: `${y(f.threshold)}%` }}>
          Limit {limit}
        </span>
        <span className="absolute top-full -translate-x-1/2 text-sm text-muted-foreground" style={{ left: `${x(f.t)}%` }}>
          now
        </span>
      </div>
      <p className="mt-6 min-h-5 text-sm text-muted-foreground">
        {readout || 'Solid: measured. Dashed: forecast.'}
      </p>
    </figure>
  )
}
