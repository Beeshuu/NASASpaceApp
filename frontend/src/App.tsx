import { motion } from 'motion/react'
import { useState } from 'react'
import { BlackBox } from '@/components/black-box'
import { DemoBar } from '@/components/demo-bar'
import { EarthCountdown } from '@/components/earth-countdown'
import { MyHealth } from '@/components/my-health'
import { MissionControl } from '@/components/mission-control'
import { SpaceWeather } from '@/components/space-weather'
import { useDemo } from '@/hooks/use-demo'
import { isMission, useMission } from '@/hooks/use-mission'
import { humanize } from '@/lib/playbook'

type TabProps = { on: boolean; current: 'page' | 'true'; group: string; onClick: () => void; children: string }

/** One selected style for views and for crew: bright text and an underline that slides to the selected tab, never a fill alone. */
function Tab({ on, current, group, onClick, children }: TabProps) {
  return (
    <button
      type="button"
      aria-current={on ? current : undefined}
      onClick={onClick}
      className={`relative min-h-11 px-1 text-sm tracking-widest whitespace-nowrap uppercase ${
        on ? 'font-bold text-foreground' : 'text-muted-foreground hover:text-foreground'
      }`}
    >
      {children}
      {on && <motion.span layoutId={group} className="absolute inset-x-0 bottom-0 h-0.5 bg-primary" transition={{ duration: 0.2, ease: 'easeOut' }} />}
    </button>
  )
}

const VIEWS = [
  ['health', 'My Health'],
  ['space', 'Space weather'],
  ['mission', 'Mission control'],
]

/** Clear this app's Access cookie, then Auth0's logout, which hands over to the team domain to end the global Access session. */
async function signOut(e: React.MouseEvent<HTMLAnchorElement>, auth0Logout: string | null) {
  if (!auth0Logout) return // no Auth0 config: the plain link ends the Access session only
  e.preventDefault()
  try {
    // redirect: 'manual' keeps the logout's Set-Cookie without following it to another origin.
    await fetch('/cdn-cgi/access/logout', { credentials: 'same-origin', redirect: 'manual' })
  } catch {
    // Auth0's logout still runs; Access then asks Auth0 again, which now asks for a login.
  }
  window.location.href = auth0Logout
}

type Mission = ReturnType<typeof useMission>
type Props = { mission: Mission; demo?: ReturnType<typeof useDemo> }

function Shell({ mission, demo }: Props) {
  const { me, crew, playbook, delayS, failed, reload } = mission
  const [selected, setSelected] = useState(() => new URLSearchParams(location.search).get('crew'))
  const [requested, setView] = useState(() => new URLSearchParams(location.search).get('view') ?? 'health')
  // Crew see their own health, mission control sees the crew as Earth does. The Worker enforces the same split.
  const views = VIEWS.filter(([id]) => id === 'space' || (id === 'health' ? me?.role === 'crew' : isMission(me)))
  // Without a view in the link, a role opens on its own screen, not on space weather.
  const view = views.some(([id]) => id === requested) ? requested : ((views.find(([id]) => id !== 'space') ?? views[0])?.[0] ?? 'space')
  const current = (crew?.some((c) => c.entity_id === selected) ? selected : crew?.[0]?.entity_id) ?? null
  const waiting = demo && demo.state?.cursor == null && view !== 'space'

  // The view and the crew member live in the URL, so a link opens the same screen.
  const go = (nextView: string, crewId: string | null) => {
    setView(nextView)
    setSelected(crewId)
    const params = new URLSearchParams()
    if (nextView !== 'health') params.set('view', nextView)
    if (crewId) params.set('crew', crewId)
    history.replaceState(null, '', `?${params}`)
  }

  return (
    <div className="mx-auto flex min-h-svh max-w-[75rem] flex-col px-4 sm:px-6">
      <header className="flex flex-wrap items-center justify-between gap-x-10 gap-y-1 border-b py-2">
        <p className="display text-base">
          Vital Orbit Pulse{demo && <span className="text-muted-foreground"> demo</span>}
        </p>
        <nav aria-label="View" className="flex flex-wrap gap-x-6">
          {views.map(([id, label]) => (
            <Tab key={id} on={view === id} current="page" group="view" onClick={() => go(id, selected)}>
              {label}
            </Tab>
          ))}
        </nav>
        {me && !me.guest && (
          <p className="label ml-auto flex items-center gap-x-4">
            <span>
              {me.email ?? 'service'}
              {me.role && <span className="text-foreground"> / {me.role.replace('_', ' ')}</span>}
            </span>
            {/* Ends this app's Access cookie, Auth0's session and the global Access session, so the next login asks who you are. */}
            <a href="/cdn-cgi/access/logout" onClick={(e) => signOut(e, me.logout_url)} className="min-h-11 content-center underline hover:text-foreground">
              Sign out
            </a>
          </p>
        )}
      </header>
      {demo && me && <DemoBar me={me} demo={demo} reload={reload} />}

      <main className="@container flex-1 py-6">
        {/* The new screen replaces the old one at once and only fades in: a swap must never wait on an animation. */}
        <motion.div
          key={`${demo?.epoch}/${me?.role}/${view}/${waiting ? '' : current}`}
          initial={{ opacity: 0, y: 8 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.18, ease: 'easeOut' }}
        >
            {me && !me.role ? (
              <div role="status" className="max-w-prose py-10">
                <h1 className="display text-2xl">No Vital Orbit role</h1>
                <p className="mt-4 text-xl">
                  {me.email} is signed in but has no role. Ask the mission admin for crew, flight surgeon or commander.
                </p>
              </div>
            ) : view === 'space' ? (
              <SpaceWeather playbook={playbook} />
            ) : waiting ? (
              <div className="frame relative flex min-h-96 items-end overflow-hidden">
                {/* decorative; the sentence below carries the meaning */}
                <img src="/limb.webp" alt="" decoding="async" className="absolute inset-0 size-full object-cover object-right" />
                {/* the scrim keeps the sentence at 4.5:1 where it crosses the lit limb */}
                <p role="status" className="relative w-full bg-linear-to-t from-background from-45% to-transparent p-6 pt-20 text-lg text-balance">
                  <span className="block max-w-md">
                    {view === 'mission'
                      ? 'Start the replay. Mission control fills in as the crew’s data reaches Earth.'
                      : 'Start the replay. Your readings appear here, live from the simulated crew.'}
                  </span>
                </p>
              </div>
            ) : view === 'mission' ? (
              demo ? (
                <div className="grid gap-x-10 gap-y-8 lg:grid-cols-[minmax(0,1fr)_18rem]">
                  <div className="@container">
                    <MissionControl crew={crew} playbook={playbook} delayS={delayS} earth />
                  </div>
                  <aside className="max-lg:order-first lg:sticky lg:top-6 lg:self-start">
                    <EarthCountdown state={demo.state} offset={demo.offset} />
                  </aside>
                </div>
              ) : (
                <MissionControl crew={crew} playbook={playbook} delayS={delayS} onPlaybook={me?.role === 'commander' ? reload : undefined} />
              )
            ) : current ? (
              <>
                {/* The Worker lists only the signed-in crew member, so there is nothing to choose between. */}
                {crew && crew.length > 1 && (
                  <nav aria-label="Crew member" className="mb-6 flex flex-wrap gap-x-6">
                    {crew.map((c) => (
                      <Tab key={c.entity_id} on={c.entity_id === current} current="true" group="crew" onClick={() => go('health', c.entity_id)}>
                        {humanize(c.entity_id)}
                      </Tab>
                    ))}
                  </nav>
                )}
                <MyHealth key={current} entityId={current} name={humanize(current)} playbook={playbook} delayS={delayS} />
                <div className="mt-12">
                  <BlackBox key={current} entityId={current} controls="none" />
                </div>
              </>
            ) : (
              <div role="status" className="max-w-prose py-10">
                <h1 className="display text-2xl">My Health</h1>
                <p className="mt-4 text-xl">
                  {failed
                    ? 'The crew list did not load. Trying again every 10 seconds.'
                    : crew
                      ? 'No crew members have reported yet.'
                      : 'Loading the crew list.'}
                </p>
                {crew && !failed && (
                  <p className="mt-2 text-muted-foreground">
                    A crew member appears here as soon as their first sensor reading arrives.
                  </p>
                )}
              </div>
            )}
        </motion.div>
      </main>
    </div>
  )
}

/** The same shell with the demo menu on top, driving the replay from this page. */
function DemoShell({ mission }: { mission: Mission }) {
  return <Shell mission={mission} demo={useDemo(mission.reload)} />
}

export default function App() {
  const mission = useMission()
  const { me } = mission
  // Guests get the demo everywhere. A signed-in commander opens it at /demo.
  const demo = me?.demo && (me.guest || (me.role === 'commander' && location.pathname.replace(/\/+$/, '') === '/demo'))
  return demo ? <DemoShell mission={mission} /> : <Shell mission={mission} />
}
