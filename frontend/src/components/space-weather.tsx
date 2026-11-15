import { type FormEvent, useEffect, useRef, useState } from 'react'
import { EventChains } from '@/components/event-chains'
import { HeliosphereMap } from '@/components/heliosphere-map'
import { ReplayTwin } from '@/components/replay-twin'
import { SPEEDS, StormScrubber } from '@/components/storm-scrubber'
import { Button } from '@/components/ui/button'
import { clock, type Playbook } from '@/lib/playbook'
import { KINDS, mmss, sky, type SwEvent } from '@/lib/space'

type Loaded = { start: string; end: string; events: SwEvent[]; missing: string[] }

const DAY = 86_400_000
const dayMs = (d: string) => Date.parse(`${d}T00:00:00Z`)
const field = 'field text-base normal-case tracking-normal text-foreground'

/** Real NASA DONKI space weather for a date range, replayed against the crew's modeled dose and twin forecast. */
export function SpaceWeather({ playbook }: { playbook: Playbook | null }) {
  const [range, setRange] = useState({ start: '2024-05-01', end: '2024-05-31' }) // the May 2024 storms
  const [data, setData] = useState<Loaded | null>(null)
  const [problem, setProblem] = useState('')
  const [loading, setLoading] = useState(false)
  const [t, setT] = useState(dayMs('2024-05-01'))
  const [playing, setPlaying] = useState(false)
  const [speed, setSpeed] = useState(SPEEDS[1].ms)
  const reducedMotion = useRef(window.matchMedia('(prefers-reduced-motion: reduce)').matches).current

  const load = async (start: string, end: string) => {
    setLoading(true)
    setProblem('')
    setPlaying(false)
    try {
      const res = await fetch(`/api/space-weather?start=${start}&end=${end}`)
      if (!res.ok) throw new Error((await res.json()).detail ?? String(res.status))
      setData(await res.json())
      setT(dayMs(start))
    } catch (e) {
      setProblem(`DONKI events did not load (${e instanceof Error ? e.message : 'no connection'}).`)
    } finally {
      setLoading(false)
    }
  }
  useEffect(() => {
    load(range.start, range.end)
    // eslint-disable-next-line react-hooks/exhaustive-deps -- the first load only; later loads come from the form
  }, [])

  const startMs = data ? dayMs(data.start) : 0
  const endMs = data ? dayMs(data.end) + DAY : 0

  useEffect(() => {
    if (!playing) return
    const advance = (ms: number) =>
      setT((now) => {
        if (now + ms < endMs) return now + ms
        setPlaying(false)
        return endMs
      })
    if (reducedMotion) {
      // No continuous motion: one jump a second, the same distance smooth playback would cover.
      const timer = window.setInterval(() => advance(speed), 1000)
      return () => window.clearInterval(timer)
    }
    let frame = 0
    let last = performance.now()
    const tick = (now: number) => {
      advance(((now - last) / 1000) * speed)
      last = now
      frame = requestAnimationFrame(tick)
    }
    frame = requestAnimationFrame(tick)
    return () => cancelAnimationFrame(frame)
  }, [playing, speed, endMs, reducedMotion])

  const submit = (e: FormEvent) => {
    e.preventDefault()
    load(range.start, range.end)
  }
  const toggle = () => {
    if (!playing && t >= endMs) setT(startMs)
    setPlaying(!playing)
  }

  const { distanceAu, lightS } = sky(t)
  // A signal crossing in under 1.5 real seconds would only flicker, so pulses show at slow speeds.
  const pulses = playing && !reducedMotion && (lightS * 1000) / speed >= 1.5
  const arrivals = data?.events.filter((e) => e.mars_arrival).toSorted((a, b) => a.mars_arrival! - b.mars_arrival!) ?? []
  const missing = data?.missing.map((k) => KINDS.find((x) => x.kind === k)?.label.toLowerCase() ?? k) ?? []

  return (
    <>
      <div className="flex flex-wrap items-end justify-between gap-x-10 gap-y-4">
        <div>
          <h1 className="display text-2xl">Space weather</h1>
          <p className="mt-2 max-w-prose text-muted-foreground">Real solar events from NASA, replayed against the crew dose model.</p>
        </div>
        <form onSubmit={submit} className="flex flex-wrap items-end gap-2">
          <label className="label flex flex-col gap-1">
            From
            <input type="date" required value={range.start} onChange={(e) => setRange({ ...range, start: e.target.value })} className={field} />
          </label>
          <label className="label flex flex-col gap-1">
            To
            <input type="date" required value={range.end} onChange={(e) => setRange({ ...range, end: e.target.value })} className={field} />
          </label>
          <Button type="submit" variant="outline" disabled={loading}>
            {loading ? 'Loading' : 'Load range'}
          </Button>
        </form>
      </div>

      <div role="status" className="mt-3">
        {problem && <p className="text-warn">{problem} Check the dates and load the range again.</p>}
        {loading && !data && <p>Loading DONKI events. The first load of a month can take a minute.</p>}
        {missing.length > 0 && (
          <p className="text-warn">DONKI did not answer for {missing.join(', ')}. Those events are left out of this replay.</p>
        )}
        {data && data.events.length === 0 && missing.length === 0 && <p>DONKI lists no events in this range.</p>}
      </div>

      {data && (
        <>
          <div className="mt-6 grid gap-x-10 gap-y-8 lg:grid-cols-2">
            <HeliosphereMap t={t} events={data.events} pulses={pulses} />
            <div className="space-y-8">
              <div>
                <p className="label">Replay time, UTC</p>
                <p className="readout mt-2 text-3xl">
                  <time dateTime={new Date(t).toISOString()}>{clock.format(t)}</time>
                </p>
                <p className="mt-2 text-muted-foreground">
                  Earth to Mars: {distanceAu.toFixed(2)} AU, {mmss(lightS)} one way.
                </p>
                <div className="mt-4 flex flex-wrap items-center gap-3">
                  <Button onClick={toggle}>{playing ? 'Pause' : t >= endMs ? 'Replay' : 'Play'}</Button>
                  <div role="group" aria-label="Replay speed" className="flex">
                    {SPEEDS.map((s) => (
                      <button
                        key={s.ms}
                        type="button"
                        aria-pressed={speed === s.ms}
                        aria-label={s.label}
                        onClick={() => setSpeed(s.ms)}
                        className="-ml-px min-h-11 border border-input px-3 text-sm first:ml-0 aria-pressed:z-10 aria-pressed:border-primary aria-pressed:bg-primary aria-pressed:font-bold aria-pressed:text-primary-foreground"
                      >
                        {s.short}
                      </button>
                    ))}
                  </div>
                </div>
              </div>
              <ReplayTwin start={data.start} end={data.end} t={t} playbook={playbook} />
            </div>
          </div>

          <div className="mt-12">
            <StormScrubber start={startMs} end={endMs} t={t} events={data.events} onSeek={setT} />
          </div>

          <div className="mt-12 grid gap-x-10 gap-y-8 lg:grid-cols-2">
            <EventChains events={data.events} t={t} />
            <section aria-labelledby="arrivals" className="sec">
              <h2 id="arrivals" className="sec-title">
                CME fronts on course for Mars
              </h2>
              {arrivals.length === 0 ? (
                <p className="mt-2">No CME in this range is aimed at Mars.</p>
              ) : (
                <ul className="mt-2">
                  {arrivals.map((e) => (
                    <li key={e.id} className="flex flex-wrap justify-between gap-x-4 border-b py-3">
                      <span>
                        Left the Sun {clock.format(e.time)} at {Math.round(e.speed!)} km/s
                      </span>
                      <span className={e.mars_arrival! <= t ? 'font-bold' : 'text-muted-foreground'}>
                        {e.mars_arrival! <= t ? 'Reached Mars' : 'Reaches Mars'} {clock.format(e.mars_arrival!)}
                      </span>
                    </li>
                  ))}
                </ul>
              )}
            </section>
          </div>
        </>
      )}

      <p className="label mt-12 normal-case">
        Events: NASA CCMC DONKI. Planet positions: Astronomy Engine. Crew dose: modeled from DONKI events.
      </p>
    </>
  )
}
