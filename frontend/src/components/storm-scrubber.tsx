import { clock } from '@/lib/playbook'
import { describe, KINDS, type SwEvent } from '@/lib/space'

export const SPEEDS = [
  { label: '1 minute per second', short: '1 min/s', ms: 60_000 },
  { label: '1 hour per second', short: '1 h/s', ms: 3_600_000 },
  { label: '6 hours per second', short: '6 h/s', ms: 21_600_000 },
]

type Props = {
  start: number
  end: number
  t: number
  events: SwEvent[]
  onSeek: (t: number) => void
}

const columns = 'grid grid-cols-[4.5rem_minmax(0,1fr)] items-center gap-x-3 sm:grid-cols-[13rem_minmax(0,1fr)]'

/** Replay control: one labelled lane of event marks per DONKI event type, and a slider for the replay time. */
export function StormScrubber({ start, end, t, events, onSeek }: Props) {
  const at = (ts: number) => `${((ts - start) / (end - start)) * 100}%`
  return (
    <section aria-labelledby="replay" className="sec">
      <h2 id="replay" className="sec-title">
        Storm timeline
      </h2>

      <div className="relative mt-3">
        {KINDS.map(({ kind, label, short }) => {
          const marks = events.filter((e) => e.type === kind)
          return (
            <div key={kind} className={`${columns} border-b py-1`}>
              <span className="label">
                <span className="sm:hidden">{short}</span>
                <span className="hidden sm:inline">{label}</span>{' '}
                <span>({marks.length})</span>
              </span>
              <div className="relative h-6">
                {marks.map((e) => (
                  <span
                    key={e.id}
                    title={`${clock.format(e.time)} UTC: ${describe(e)}`}
                    // A mark the replay has not reached yet is dimmed.
                    className={`absolute top-0.5 h-5 w-0.5 ${e.time <= t ? 'bg-foreground' : 'bg-input'}`}
                    style={{ left: at(e.time) }}
                  />
                ))}
              </div>
            </div>
          )
        })}
        <div className={`${columns} pointer-events-none absolute inset-0`}>
          <span />
          <div className="relative h-full">
            <span className="absolute inset-y-0 w-px bg-primary" style={{ left: at(t) }} />
          </div>
        </div>
      </div>

      <div className={`${columns} mt-2`}>
        <label htmlFor="replay-time" className="label">
          Time
        </label>
        <input
          id="replay-time"
          type="range"
          min={start}
          max={end}
          step={600_000}
          value={t}
          onChange={(e) => onSeek(Number(e.target.value))}
          aria-valuetext={`${clock.format(t)} UTC`}
          className="h-11 w-full accent-(--primary)"
        />
      </div>
    </section>
  )
}
