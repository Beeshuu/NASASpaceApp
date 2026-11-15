import { useEffect, useRef, useState } from 'react'
import { ForecastChart } from '@/components/forecast-chart'
import type { Status } from '@/hooks/use-live-readings'
import { StatusMark } from '@/components/status-mark'
import { clock, forecastTime, heldActions, humanize, type Playbook } from '@/lib/playbook'

type Twin = { at: number; dose_rate: number; cumulative_dose: number; status: Status }

const number = new Intl.NumberFormat('en', { maximumFractionDigits: 2 })
const HALF_HOUR = 1_800_000

/** The playbook engine and its twin at the replay time, fed the crew dose modeled from DONKI events. */
type Props = { start: string; end: string; t: number; playbook: Playbook | null }

export function ReplayTwin({ start, end, t, playbook }: Props) {
  const [twin, setTwin] = useState<Twin | null>(null)
  const [problem, setProblem] = useState('')
  const at = Math.floor(t / HALF_HOUR) * HALF_HOUR // the model steps every half hour, so ask once per step
  const active = playbook ? `${playbook.name}@${playbook.version}` : null // a playbook switch asks again

  const lastSent = useRef(0)
  const sent = useRef(0) // request counter
  const shown = useRef(0) // counter of the answer on screen, so a slow older answer never replaces a newer one

  useEffect(() => {
    // At most one request every 400 ms. During fast playback the panel follows a few steps behind
    // instead of flooding the Worker or never updating.
    const wait = Math.max(0, 400 - (performance.now() - lastSent.current))
    const timer = window.setTimeout(async () => {
      lastSent.current = performance.now()
      const mine = ++sent.current
      try {
        const res = await fetch(`/api/space-weather/twin?start=${start}&end=${end}&at=${new Date(at).toISOString()}`)
        if (res.status === 409) return setProblem('The active playbook has no space weather section, so no dose is modeled.')
        if (!res.ok) throw new Error(String(res.status))
        const answer: Twin = await res.json()
        if (mine < shown.current) return
        shown.current = mine
        setTwin(answer)
        setProblem('')
      } catch {
        setProblem('The dose model did not answer for this time. It retries when the replay moves.')
      }
    }, wait)
    return () => window.clearTimeout(timer)
  }, [start, end, at, active])

  const alert = twin?.status.alerts[0]
  const checklist = alert?.checklist ? playbook?.checklists[alert.checklist] : undefined
  const forecast = twin?.status.forecasts[0]
  const spec = forecast && playbook?.domains[forecast.domain]?.indicators[forecast.metric]

  return (
    <section aria-labelledby="dose" className="sec">
      <h2 id="dose" className="sec-title">
        Crew dose, modeled from DONKI events
      </h2>
      <p className="mt-2 text-muted-foreground">A model, not a measurement.</p>
      {problem && (
        <p role="alert" className="mt-3 text-warn">
          {problem}
        </p>
      )}
      {!twin ? (
        !problem && <p role="status" className="mt-3">Running the dose model.</p>
      ) : (
        <>
          <dl className="mt-3 grid grid-cols-2 gap-px border bg-border">
            <div className="bg-background p-3">
              <dt className="label">Dose rate now</dt>
              <dd className="pt-3">
                <span className="readout text-2xl">{number.format(twin.dose_rate)}</span>{' '}
                <span className="text-sm text-muted-foreground">mSv/day</span>
              </dd>
            </div>
            <div className="bg-background p-3">
              <dt className="label">Dose since {start}</dt>
              <dd className="pt-3">
                <span className="readout text-2xl">{number.format(twin.cumulative_dose)}</span>{' '}
                <span className="text-sm text-muted-foreground">
                  {forecast ? `of ${number.format(forecast.threshold)} mSv budget` : 'mSv'}
                </span>
              </dd>
            </div>
          </dl>

          <div role="status" className="mt-4">
            {alert ? (
              <>
                <StatusMark playbook={playbook} severity={alert.severity} />
                <p className="mt-1 text-xl font-bold">{alert.message}</p>
                {alert.queued?.length ? (
                  <p className="mt-1">Sent to Earth for review first: {heldActions(playbook, alert.queued)}.</p>
                ) : (
                  alert.checklist && <p className="mt-1">The edge acted at once, without waiting for Earth.</p>
                )}
                <p className="text-muted-foreground">
                  {alert.eta && alert.eta > alert.ts ? `Forecast for ${forecastTime(alert.eta, alert.ts)}.` : `Since ${clock.format(alert.ts)} UTC.`}
                </p>
              </>
            ) : (
              <StatusMark playbook={playbook} />
            )}
          </div>
          {checklist && (
            <div className="mt-4 border-t pt-3">
              <p className="font-bold">Checklist: {checklist.title}</p>
              <ol className="mt-1 list-decimal pl-5">
                {checklist.steps.map((s) => (
                  <li key={s} className="py-1">
                    {s}
                  </li>
                ))}
              </ol>
              <p className="mt-1 text-sm text-muted-foreground">This is a replay, so steps are shown and not logged.</p>
            </div>
          )}

          {forecast && (
            <div className="mt-6">
              <ForecastChart
                forecast={forecast}
                label={spec?.label ?? humanize(forecast.metric)}
                unit={spec?.unit}
                missionStart={playbook?.mission?.start}
              />
            </div>
          )}
        </>
      )}
    </section>
  )
}
