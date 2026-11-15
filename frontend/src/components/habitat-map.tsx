import { createRef, type RefObject, useMemo, useRef } from 'react'
import { AnimatedBeam } from '@/components/ui/animated-beam'
import { type HabitatCrew, useHabitat } from '@/hooks/use-habitat'
import { humanize } from '@/lib/playbook'

const source = (c: HabitatCrew) => c.own.length > 0
const state = (c: HabitatCrew) => (source(c) ? 'Sensor breach' : c.prewarned.length ? 'Pre-warned' : 'Clear')

/** One module: its crew as chips, and a beam from whoever's sensor breached to each mate it has pre-warned. */
function ModuleCard({ name, crew }: { name: string; crew: HabitatCrew[] }) {
  const box = useRef<HTMLDivElement>(null)
  const ids = crew.map((c) => c.entity_id).join()
  const refs = useMemo(() => new Map(ids.split(',').map((id) => [id, createRef<HTMLDivElement>()])), [ids])
  const warned = crew.flatMap((c) => c.prewarned.map((w) => ({ from: w.from, to: c.entity_id })))

  return (
    <section aria-label={`${name} module`} className="border p-4">
      <h3 className="display text-base">{name}</h3>
      <div ref={box} className="relative mt-4 flex flex-wrap justify-around gap-6">
        {crew.map((c) => (
          <div
            key={c.entity_id}
            ref={refs.get(c.entity_id) as RefObject<HTMLDivElement>}
            className={`relative z-10 min-w-28 border bg-background p-3 text-center ${state(c) === 'Clear' ? '' : 'border-warn'}`}
          >
            <p className="font-bold">{humanize(c.entity_id)}</p>
            <p className={state(c) === 'Clear' ? 'text-sm text-muted-foreground' : 'text-sm text-warn'}>{state(c)}</p>
          </div>
        ))}
        {warned.map((w, i) => {
          const from = refs.get(w.from)
          const to = refs.get(w.to)
          return from && to ? (
            <AnimatedBeam key={`${w.from}-${w.to}`} containerRef={box} fromRef={from} toRef={to} curvature={30} delay={i * 0.3} />
          ) : null
        })}
      </div>
      {crew.some(source) && (
        <p role="status" className="mt-3 text-sm">
          {crew
            .filter(source)
            .map((c) => `${humanize(c.entity_id)}: ${c.own[0].message}`)
            .join(' ')}
        </p>
      )}
    </section>
  )
}

/** Habitat map: modules as cards with the crew placed in them. A group-wide warning spreads along the beams. */
export function HabitatMap() {
  const crew = useHabitat()
  const modules = Map.groupBy(crew ?? [], (c) => c.module ?? 'Unplaced')
  return (
    <section aria-labelledby="habitat" className="sec">
      <h2 id="habitat" className="sec-title">
        Habitat
      </h2>
      {!crew && <p role="status">Loading the habitat.</p>}
      {crew && crew.length === 0 && <p role="status">No crew members have reported yet.</p>}
      <div className="mt-3 grid gap-4 sm:grid-cols-2">
        {[...modules].map(([m, c]) => (
          <ModuleCard key={m} name={humanize(m)} crew={c} />
        ))}
      </div>
    </section>
  )
}
