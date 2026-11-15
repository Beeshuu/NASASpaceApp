import { useMemo } from 'react'
import { clock } from '@/lib/playbook'
import { chains, describe, type SwEvent } from '@/lib/space'

const SHOWN = 5

/** Events DONKI links as one storm, in time order. Each step lights up as the replay reaches it. */
export function EventChains({ events, t }: { events: SwEvent[]; t: number }) {
  const all = useMemo(() => chains(events), [events])
  // The chains under way at the replay time, newest first.
  const begun = all.filter((c) => c[0].time <= t).toSorted((a, b) => b[0].time - a[0].time)

  return (
    <section aria-labelledby="chains" className="sec">
      <h2 id="chains" className="sec-title">
        Linked events
      </h2>
      <p className="mt-2 text-muted-foreground">A flare, the CME it launched, and what followed.</p>
      {begun.length === 0 ? (
        <p role="status" className="mt-3">
          {all.length === 0
            ? 'DONKI links no events to each other in this range.'
            : 'No linked events have started yet at this point in the replay.'}
        </p>
      ) : (
        <ul className="mt-3 space-y-4">
          {begun.slice(0, SHOWN).map((chain) => {
            const reached = chain.filter((e) => e.time <= t)
            return (
              <li key={chain[0].id}>
                <ol className="flex flex-wrap gap-x-2 gap-y-1">
                  {chain.map((e, i) => {
                    const state = e.time > t ? 'ahead' : e === reached.at(-1) ? 'latest' : 'past'
                    return (
                      <li
                        // keyed by state so the highlight plays when the replay reaches this step
                        key={`${e.id}:${state}`}
                        className={`rounded-sm border px-2 py-1 text-sm ${
                          state === 'ahead' ? 'text-muted-foreground' : state === 'latest' ? 'value-changed border-signal font-bold' : ''
                        }`}
                      >
                        <span className="text-muted-foreground">{i + 1}.</span> {clock.format(e.time)}: {describe(e)}
                      </li>
                    )
                  })}
                </ol>
              </li>
            )
          })}
        </ul>
      )}
      {begun.length > SHOWN && (
        <p className="mt-3 text-sm text-muted-foreground">Showing the {SHOWN} most recent of {begun.length} linked groups.</p>
      )}
    </section>
  )
}
