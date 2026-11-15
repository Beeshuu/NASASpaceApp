import { useCallback, useEffect, useRef, useState } from 'react'

/** A date a visitor can replay. Times are epoch ms of mission time. */
export type Scenario = { id: string; start: number; end: number; title: string; about: string }

/** /api/demo/state: the replay cursor and the Earth link of the crew member the countdown follows. */
export type DemoState = {
  now: number // server clock, epoch ms
  cursor: number | null // mission time of the last replayed step; null before Start
  start: number
  end: number
  focus: string
  crew: string[] // the simulated crew a guest can view as
  scenario: string // id of the replay loaded, or of the default before Start
  scenarios: Scenario[]
  delay_s: number // Earth delay in force: shortened for the replay unless the playbook fixes its own
  real_delay_s: number // the real Earth to Mars light time on the replay date
  playbook_delay: boolean // the active playbook fixes its own delay, so the replay does not shorten it
  alert_due: number | null // when the first alert still on its way reaches Earth
  alert_received: number | null
  pending: number[] // sampled due times of messages on their way
}

/** /api/demo/prepare. `ready`: the replay month is stored. `missing`: "KIND YYYY-MM" chunks DONKI did not answer for. */
export type Prepared = { events: number; sep: number; missing: string[]; ready: boolean } | 'loading' | 'failed'

async function call(path: string, body?: object) {
  const res = await fetch(
    `/api/demo/${path}`,
    body && { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify(body) },
  )
  const data = await res.json().catch(() => ({}))
  if (!res.ok) throw Object.assign(new Error(data.detail ?? `HTTP ${res.status}`), { status: res.status })
  return data
}

/**
 * Drives the scripted replay from the page: one step a second while running, otherwise the state once a second.
 * Every call goes to our own Worker. DONKI data is cached by `prepare` before Start is offered.
 */
export function useDemo(onReset: () => void) {
  const [state, setState] = useState<DemoState | null>(null)
  const [offset, setOffset] = useState(0) // server clock minus this clock
  const [prepared, setPrepared] = useState<Prepared>('loading')
  const [running, setRunning] = useState(false)
  const [busy, setBusy] = useState(false)
  const [off, setOff] = useState(false) // DEMO_MODE is not set on the Worker
  const [problem, setProblem] = useState<string | null>(null)
  const [epoch, setEpoch] = useState(0) // bumped on Start and Reset, so the views remount with clean state
  const runningRef = useRef(false)
  const busyRef = useRef(false)
  const tickRef = useRef<Promise<void>>(Promise.resolve())

  const run = (on: boolean) => {
    runningRef.current = on
    setRunning(on)
  }

  const apply = useCallback((s: DemoState) => {
    setState(s)
    setOffset(s.now - Date.now())
    if (s.cursor !== null && s.cursor >= s.end) run(false)
  }, [])

  const prepare = useCallback(async () => {
    setPrepared('loading')
    try {
      setPrepared(await call('prepare', {}))
    } catch (e) {
      if ((e as { status?: number }).status === 404) setOff(true)
      setPrepared('failed')
    }
  }, [])

  useEffect(() => {
    prepare()
    let stopped = false
    let timer: number | undefined
    const tick = async () => {
      if (!busyRef.current) {
        const p = (async () => {
          try {
            apply(runningRef.current ? await call('step', {}) : await call('state'))
            setProblem(null)
          } catch (e) {
            const status = (e as { status?: number }).status
            if (status === 404) setOff(true)
            if (status === 409) run(false) // reset elsewhere, or DONKI data went missing
            setProblem(`${(e as Error).message} Retrying every second.`)
          }
        })()
        tickRef.current = p
        await p
      }
      if (!stopped) timer = window.setTimeout(tick, 1000)
    }
    tick()
    return () => {
      stopped = true
      window.clearTimeout(timer)
    }
  }, [apply, prepare])

  /** Runs one control action with the replay loop held, so no step lands in the middle of a reset. */
  const act = async (path: string, body: object, after?: () => void) => {
    busyRef.current = true
    setBusy(true)
    try {
      await tickRef.current
      apply(await call(path, body))
      setProblem(null)
      after?.()
    } catch (e) {
      setProblem((e as Error).message)
    } finally {
      busyRef.current = false
      setBusy(false)
    }
  }

  const fresh = () => {
    setEpoch((n) => n + 1)
    onReset()
  }

  return {
    state,
    offset,
    prepared,
    prepare,
    running,
    busy,
    off,
    problem,
    epoch,
    start: (scenario: string) => {
      run(false)
      return act('start', { scenario }, () => {
        fresh()
        run(true)
      })
    },
    pause: () => run(false),
    resume: () => run(true),
    reset: () => {
      run(false)
      return act('reset', {}, fresh)
    },
  }
}
