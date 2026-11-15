import { useEffect, useState } from 'react'
import { clock } from '@/lib/playbook'

type Incident = {
  id: string
  message: string
  stage: 'starting' | 'notified' | 'sheltered' | 'paged'
  status: string // from Cloudflare Workflows: queued, running, waiting, complete, errored, ...
  timeout: string
  created_ts: number
}

const STEPS: { stage: Incident['stage']; label: string }[] = [
  { stage: 'notified', label: 'Crew told to shelter' },
  { stage: 'sheltered', label: 'Shelter checklist complete' },
  { stage: 'paged', label: 'Commander paged' },
]

/** The incident-response Workflow for this crew member's newest critical alert, as Cloudflare Workflows reports it. */
export function IncidentStatus({ entityId }: { entityId: string }) {
  const [incident, setIncident] = useState<Incident | null>(null)

  useEffect(() => {
    let stopped = false
    const load = async () => {
      try {
        const res = await fetch(`/api/astronauts/${encodeURIComponent(entityId)}/incident`)
        if (res.ok && !stopped) setIncident(await res.json())
      } catch {
        // keep the last known state; the next poll retries
      }
    }
    load()
    const timer = window.setInterval(load, 5000)
    return () => {
      stopped = true
      window.clearInterval(timer)
    }
  }, [entityId])

  if (!incident) return null
  const reached = (s: Incident['stage']) =>
    s === incident.stage || (s === 'notified' && incident.stage !== 'starting')
  const waiting = incident.stage === 'notified'

  return (
    <section aria-labelledby="incident" className="sec mt-6">
      <h2 id="incident" className="sec-title">
        Incident response
      </h2>
      <p className="mt-2">
        {incident.message} <span className="text-muted-foreground">Since {clock.format(incident.created_ts)} UTC.</span>
      </p>
      <ol className="mt-2">
        {STEPS.filter((s) => s.stage !== 'paged' || incident.stage === 'paged').map((s) => (
          <li key={s.stage} className={reached(s.stage) ? 'font-bold' : 'text-muted-foreground'}>
            {reached(s.stage) ? '✓ ' : '○ '}
            {s.label}
          </li>
        ))}
      </ol>
      <p role="status" className="mt-2 text-sm text-muted-foreground">
        Workflow {incident.status}.
        {waiting && ` Finish the shelter checklist within ${incident.timeout}, or the commander is paged.`}
      </p>
    </section>
  )
}
