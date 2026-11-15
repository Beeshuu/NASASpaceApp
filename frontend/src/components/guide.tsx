import { motion } from 'motion/react'
import { useEffect, useState } from 'react'
import { buttonVariants } from '@/components/ui/button'
import type { DemoState } from '@/hooks/use-demo'

const when = new Intl.DateTimeFormat('en-GB', { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit', timeZone: 'UTC' })

const STEPS = [
  'Choose whose screen you see: a crew member, the commander or the flight surgeon.',
  'Choose a date from the list below.',
  'Press Start replay. Each second replays 30 mission minutes.',
]

/** /guide: how to run the demo, and the dates it can replay. */
export function Guide() {
  const [state, setState] = useState<DemoState | 'off' | 'failed' | null>(null)
  useEffect(() => {
    fetch('/api/demo/state')
      .then(async (res) => setState(res.ok ? await res.json() : res.status === 404 ? 'off' : 'failed'))
      .catch(() => setState('failed'))
  }, [])

  return (
    <main className="mx-auto max-w-3xl px-4 py-10 sm:px-6">
      <p className="display text-base">
        Vital Orbit Pulse <span className="text-muted-foreground">demo</span>
      </p>
      <h1 className="display mt-10 text-2xl">Demo guide</h1>
      <p className="mt-4 max-w-prose text-lg">
        A simulated crew on the way to Mars, replayed against real NASA space weather from May 2024.
      </p>

      <ol className="mt-8 space-y-3">
        {STEPS.map((step, i) => (
          <li key={step} className="flex gap-4">
            <span aria-hidden className="readout w-6 text-muted-foreground">
              {i + 1}
            </span>
            <span className="max-w-prose">{step}</span>
          </li>
        ))}
      </ol>
      {typeof state === 'object' && state && (
        <p className="mt-4 max-w-prose text-muted-foreground">
          Earth receives each message {state.delay_s} {state.delay_s === 1 ? 'second' : 'seconds'} after the crew sends it.{' '}
          {state.playbook_delay
            ? 'The active playbook sets that delay.'
            : `The real delay to Mars on these dates is about ${Math.round(state.real_delay_s / 60)} minutes.`}
        </p>
      )}

      <section aria-labelledby="dates" className="sec mt-12">
        <h2 id="dates" className="sec-title">
          Dates you can replay
        </h2>
        {state === null && <p role="status" className="mt-4">Loading the dates.</p>}
        {state === 'off' && <p role="status" className="mt-4">Demo mode is off on this server.</p>}
        {state === 'failed' && <p role="status" className="mt-4 text-warn">The dates did not load. Reload the page to try again.</p>}
        {typeof state === 'object' && state && (
          <ul>
            {state.scenarios.map((s, i) => (
              <motion.li
                key={s.id}
                initial={{ opacity: 0, y: 12 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ duration: 0.3, ease: 'easeOut', delay: i * 0.07 }}
                className="grid gap-x-8 gap-y-3 border-b py-6 sm:grid-cols-[minmax(0,1fr)_auto] sm:items-center"
              >
                <div>
                  <h3 className="display text-lg">{s.title}</h3>
                  <p className="label mt-1">
                    {when.format(s.start)} to {when.format(s.end)} UTC
                  </p>
                  <p className="mt-2 max-w-prose">{s.about}</p>
                </div>
                <a href={`/demo?date=${s.id}`} className={buttonVariants({ variant: 'outline' })}>
                  Use this date
                </a>
              </motion.li>
            ))}
          </ul>
        )}
      </section>

      <p className="mt-10">
        <a href="/demo" className={buttonVariants()}>
          Open the demo
        </a>
      </p>
    </main>
  )
}
