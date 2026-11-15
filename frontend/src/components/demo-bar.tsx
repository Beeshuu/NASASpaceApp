import { motion } from 'motion/react'
import { useEffect, useState } from 'react'
import { PlaybookSwitcher } from '@/components/playbook-switcher'
import { Button } from '@/components/ui/button'
import type { Prepared, Scenario, useDemo } from '@/hooks/use-demo'
import type { Me, Role } from '@/hooks/use-mission'
import { clock, humanize } from '@/lib/playbook'

const ROLES: [Role, string][] = [
  ['crew', 'Crew member'],
  ['commander', 'Commander'],
  ['flight_surgeon', 'Flight surgeon'],
]

const day = new Intl.DateTimeFormat('en-GB', { day: 'numeric', month: 'short', year: 'numeric', timeZone: 'UTC' })
const scenarioDay = (s: Scenario) => day.format(s.start)

/** The Worker reads the guest's role and crew member from these on every request, so the rules it enforces follow the pick. */
const remember = (name: string, value: string) => {
  document.cookie = `${name}=${value}; path=/; max-age=604800; samesite=lax`
}

function DonkiStatus({ prepared, retry }: { prepared: Prepared; retry: () => void }) {
  if (prepared === 'loading') return <span>Caching NASA DONKI data for May 2024.</span>
  if (prepared === 'failed' || !prepared.ready)
    return (
      <span className="text-warn">
        DONKI data for May 2024 is not cached
        {prepared !== 'failed' && ` (missing ${prepared.missing.join(', ')})`}. NASA did not answer.{' '}
        <Button variant="outline" onClick={retry}>
          Try again
        </Button>
      </span>
    )
  return (
    <span className="text-muted-foreground">
      NASA DONKI, May 2024: {prepared.events} events, {prepared.sep} particle events cached.
      {prepared.missing.length > 0 && ` Not cached: ${prepared.missing.join(', ')}.`}
    </span>
  )
}

/** Reset wipes all crew data and the black box, so it takes two presses. The second must come within four seconds. */
function ResetButton({ disabled, onReset }: { disabled: boolean; onReset: () => void }) {
  const [armed, setArmed] = useState(false)
  useEffect(() => {
    if (!armed) return
    const timer = window.setTimeout(() => setArmed(false), 4000)
    return () => window.clearTimeout(timer)
  }, [armed])
  return (
    <Button
      variant="destructive"
      disabled={disabled}
      onClick={() => {
        if (armed) onReset()
        setArmed(!armed)
      }}
    >
      {armed ? 'Press again to clear all data' : 'Reset'}
    </Button>
  )
}

type Props = { me: Me; demo: ReturnType<typeof useDemo>; reload: () => void }

/** The demo menu: start a replay of a chosen date, and for a guest, choose whose screen to see. */
export function DemoBar({ me, demo, reload }: Props) {
  const { state, prepared } = demo
  const ready = prepared !== 'loading' && prepared !== 'failed' && prepared.ready
  const started = state?.cursor != null
  const ended = started && state.cursor! >= state.end
  // A date from the guide page's link, until the visitor picks another here.
  const [pick, setPick] = useState(() => new URLSearchParams(location.search).get('date'))
  const scenario = state?.scenarios.find((s) => s.id === pick) ?? state?.scenarios.find((s) => s.id === state.scenario)
  const loaded = started && scenario?.id === state.scenario

  const viewAs = (role: Role, crewId = me.crew_id ?? state?.focus ?? '') => {
    remember('vop_role', role)
    remember('vop_crew', crewId)
    reload()
  }

  // Fixed width: the label changes (Start, Pause, Resume), the controls beside it must not move.
  const main = 'w-44'

  return (
    <div className="border-b py-2">
      <div className="flex flex-wrap items-center gap-x-6 gap-y-2">
        {!loaded || ended ? (
          <Button className={main} disabled={!ready || demo.busy || !scenario} onClick={() => scenario && demo.start(scenario.id)}>
            {demo.busy ? 'Loading' : loaded ? 'Replay again' : 'Start replay'}
          </Button>
        ) : demo.running ? (
          <Button variant="outline" className={main} onClick={demo.pause}>
            Pause
          </Button>
        ) : (
          <Button className={main} disabled={demo.busy} onClick={demo.resume}>
            Resume
          </Button>
        )}

        <div className="flex max-w-full min-w-0 items-center gap-2">
          <label htmlFor="demo-date" className="label">
            Date
          </label>
          <select id="demo-date" className="field min-w-0 flex-1" value={scenario?.id ?? ''} disabled={demo.busy} onChange={(e) => setPick(e.target.value)}>
            {state?.scenarios.map((s) => (
              <option key={s.id} value={s.id}>
                {scenarioDay(s)}: {s.title}
              </option>
            ))}
          </select>
        </div>

        {me.guest && (
          <div role="group" aria-label="View as" className="flex max-w-full flex-wrap items-center gap-2">
            <span className="label">View as</span>
            <div className="flex">
              {ROLES.map(([role, label]) => (
                <button
                  key={role}
                  type="button"
                  aria-pressed={me.role === role}
                  onClick={() => viewAs(role)}
                  className="relative -ml-px min-h-11 border border-input px-3 text-sm first:ml-0 hover:bg-muted aria-pressed:z-10 aria-pressed:border-primary aria-pressed:font-bold aria-pressed:text-primary-foreground aria-pressed:hover:bg-transparent"
                >
                  {me.role === role && (
                    <motion.span layoutId="view-as" className="absolute inset-0 bg-primary" transition={{ duration: 0.2, ease: 'easeOut' }} />
                  )}
                  <span className="relative">{label}</span>
                </button>
              ))}
            </div>
          </div>
        )}
      </div>

      {/* Its own row, so what a role adds (crew picker, playbook) never pushes the controls above around. */}
      <div className="mt-2 flex flex-wrap items-center gap-x-6 gap-y-2">
        {/* The slot keeps its size when empty (flight surgeon), so the items after it stay put. */}
        <div className="flex min-h-11 min-w-72 items-center">
        {me.role === 'crew' && state && (
          <div className="flex items-center gap-2">
            <label htmlFor="demo-crew" className="label">
              Crew member
            </label>
            <select id="demo-crew" className="field" value={me.crew_id ?? ''} onChange={(e) => viewAs('crew', e.target.value)}>
              {state.crew.map((id) => (
                <option key={id} value={id}>
                  {humanize(id)}
                </option>
              ))}
            </select>
          </div>
        )}
        {me.role === 'commander' && <PlaybookSwitcher onSwitched={reload} only={['mars-transit', 'iss-leo']} />}
        </div>

        <p className="label ml-auto">
          Mission time <span className="text-foreground">{started ? `${clock.format(state.cursor!)} UTC` : 'not started'}</span>
        </p>
        <a href="/guide" className="min-h-11 content-center text-sm underline underline-offset-4 hover:text-foreground">
          Demo guide
        </a>
        <ResetButton disabled={demo.busy} onReset={demo.reset} />
      </div>

      <div role="status" className="pt-2 text-sm">
        <DonkiStatus prepared={prepared} retry={demo.prepare} />
        {demo.problem && <p className="text-warn">{demo.problem}</p>}
        {started && !ended && !demo.running && <p className="text-muted-foreground">Paused. Messages already sent still reach Earth.</p>}
        {ended && <p className="text-muted-foreground">The replay has reached its end. Start it again, or pick another date.</p>}
      </div>
    </div>
  )
}
