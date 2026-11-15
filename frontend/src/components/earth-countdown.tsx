import { useEffect, useState } from 'react'
import type { DemoState } from '@/hooks/use-demo'

const mmss = (ms: number) => {
  const s = Math.ceil(ms / 1000)
  return `${String(Math.floor(s / 60)).padStart(2, '0')}:${String(s % 60).padStart(2, '0')}`
}

const day = new Intl.DateTimeFormat('en-GB', { day: 'numeric', month: 'long', year: 'numeric', timeZone: 'UTC' })

type Props = {
  state: DemoState | null
  offset: number // server clock minus this clock
}

/** The centre of the demo: how long until Earth has the alert the crew already acted on, and the messages in flight. */
export function EarthCountdown({ state, offset }: Props) {
  const [, tick] = useState(0)
  useEffect(() => {
    const timer = window.setInterval(() => tick((n) => n + 1), 250)
    return () => window.clearInterval(timer)
  }, [])

  const now = Date.now() + offset
  const delayMs = (state?.delay_s ?? 0) * 1000
  const remaining = state?.alert_due ? Math.max(0, state.alert_due - now) : null
  // Where a message is between Mars (0) and Earth (1).
  const along = (due: number) => (delayMs > 0 ? Math.min(1, Math.max(0, 1 - (due - now) / delayMs)) : 1)
  const x = (due: number) => 34 + along(due) * 172

  let label: string
  let big: string
  let note: string
  if (!state || state.cursor === null) {
    ;[label, big, note] = ['Earth link', state ? mmss(state.delay_s * 1000) : '--:--', 'Start the replay to send data from Mars.']
  } else if (remaining !== null) {
    ;[label, big, note] = [
      remaining > 0 ? 'Earth receives this in' : 'Arriving at Earth now',
      mmss(remaining),
      'The crew already has the alert and the shelter checklist. Earth still shows the old data.',
    ]
  } else if (state.alert_received) {
    ;[label, big, note] = ['Earth has received the alert', '00:00', 'Mission control sees the spike and the black-box entries. They are ready for review.']
  } else {
    ;[label, big, note] = ['Earth is behind by', mmss(delayMs), 'Waiting for a space weather event.']
  }

  const on = day.format(state?.cursor ?? state?.start ?? Date.now())
  const source = !state
    ? ''
    : state.playbook_delay
      ? `Fixed delay of ${state.delay_s} s, set by the active playbook.`
      : state.delay_s === state.real_delay_s
        ? `Real Earth to Mars light time on ${on}.`
        : `Shortened to ${state.delay_s} s for this replay. The real light time on ${on} is ${mmss(state.real_delay_s * 1000)}.`

  const inFlight = Boolean(state?.pending.length || state?.alert_due)

  return (
    <section aria-labelledby="countdown" className="sec">
      <h2 id="countdown" className="sec-title">
        {label}
      </h2>
      <p aria-hidden className="readout mt-3 text-6xl">
        {big}
      </p>
      {/* Screen readers get the time in half-minute steps, not four updates a second. */}
      <p role="status" className="sr-only">
        {label} {remaining !== null ? mmss(Math.ceil(remaining / 30_000) * 30_000) : big}
      </p>
      <p className="mt-3">{note}</p>
      <p className="mt-2 text-sm text-muted-foreground">{source}</p>

      <svg viewBox="0 0 240 56" className="mt-6 w-full" role="img" aria-label={`${state?.pending.length ? 'Messages on their way' : 'No messages on their way'} from Mars to Earth.`}>
        <line x1="34" y1="24" x2="206" y2="24" className={`stroke-input ${inFlight ? 'beam' : ''}`} strokeWidth="1.5" strokeDasharray="4 4" />
        {/* Mars is a ring and Earth a disc, the same as on the space weather map. Neither uses a status colour. */}
        <circle cx="18" cy="24" r="11" className="fill-background stroke-foreground" strokeWidth="2" />
        <circle cx="222" cy="24" r="12" className="fill-foreground" />
        <text x="18" y="52" textAnchor="middle" className="fill-muted-foreground text-[10px] tracking-widest uppercase">
          Mars
        </text>
        <text x="222" y="52" textAnchor="middle" className="fill-muted-foreground text-[10px] tracking-widest uppercase">
          Earth
        </text>
        {state?.pending.map((due, i) =>
          along(due) < 1 ? (
            <circle
              key={i}
              cx="0"
              cy="24"
              r="2.5"
              className="fill-foreground motion-safe:transition-transform motion-safe:duration-250 motion-safe:ease-linear"
              style={{ transform: `translateX(${x(due)}px)` }}
            />
          ) : null,
        )}
        {state?.alert_due && along(state.alert_due) < 1 && (
          <rect
            x="-6"
            y="18"
            width="12"
            height="12"
            className="fill-destructive stroke-background motion-safe:transition-transform motion-safe:duration-250 motion-safe:ease-linear"
            strokeWidth="2"
            style={{ transform: `translateX(${x(state.alert_due)}px)` }}
          />
        )}
      </svg>
      {inFlight && (
        <p className="mt-1 text-sm text-muted-foreground">
          {state?.alert_due ? 'Square: the alert. Dots: other readings.' : 'Dots: readings on their way.'}
        </p>
      )}
    </section>
  )
}
