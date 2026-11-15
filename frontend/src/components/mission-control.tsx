import { useCallback, useEffect, useState } from 'react'
import { BlackBox } from '@/components/black-box'
import { DomainPanel } from '@/components/domain-panel'
import { HabitatMap } from '@/components/habitat-map'
import { ForecastChart } from '@/components/forecast-chart'
import { PlaybookSwitcher } from '@/components/playbook-switcher'
import { ReviewQueue } from '@/components/review-queue'
import { StatusMark } from '@/components/status-mark'
import { UnderTheHood } from '@/components/under-the-hood'
import { type Alert, useLiveReadings } from '@/hooks/use-live-readings'
import { clock, heldActions, humanize, type Playbook } from '@/lib/playbook'
import { mmss, sky } from '@/lib/space'

type CrewMember = { entity_id: string; module?: string | null }
type Props = {
  crew: CrewMember[] | null
  playbook: Playbook | null
  delayS: number | null
  /** Demo mode: the black box and review queue show only entries that have reached Earth. */
  earth?: boolean
  /** Shows the playbook switcher and is called after a switch. */
  onPlaybook?: () => void
}

const roles = (rs: string[] | undefined) => (rs ?? []).map((r) => r.replace(/_/g, ' ')).join(', ')

/** What the edge did about an alert without waiting for Earth, and what it is still waiting on. */
function edgeActions(a: Alert, playbook: Playbook | null) {
  return [
    a.paged?.length && `Paged ${roles(a.paged)}.`,
    a.notified?.length && `Notified ${roles(a.notified)}.`,
    a.queued?.length && `Waiting for your review: ${heldActions(playbook, a.queued)}.`,
  ]
    .filter(Boolean)
    .join(' ')
}

/** One crew member as Earth sees them: their shared data, one comm delay late. */
type CardProps = { member: CrewMember; playbook: Playbook | null; delayS: number | null; onLedger: () => void }

function CrewCard({ member, playbook, delayS: fixed, onLedger }: CardProps) {
  const id = member.entity_id
  const name = humanize(id)
  const { readings, status, link, withheld, ledgerSeq } = useLiveReadings(id, true)
  // New black-box entries just reached Earth with this message: reload the log and the queue now, not on the next poll.
  useEffect(() => {
    if (ledgerSeq !== null) onLedger()
  }, [ledgerSeq, onLedger])
  const newest = readings.reduce((max, r) => Math.max(max, r.ts), 0)
  const delayS = fixed ?? (newest ? Math.round(sky(newest).lightS) : null)
  const top = status?.alerts[0]
  const label = (d: string, m: string) => playbook?.domains[d]?.indicators[m]?.label ?? humanize(m)
  const byDomain = Map.groupBy(readings.toSorted((a, b) => a.metric.localeCompare(b.metric)), (r) => r.domain)
  const domains = Object.keys(playbook?.domains ?? {}).filter((d) => byDomain.has(d))

  return (
    <section aria-labelledby={`crew-${id}`} className="sec">
      <div className="flex flex-wrap items-center justify-between gap-x-6 gap-y-1">
        <h2 id={`crew-${id}`} className="display text-lg">
          {name}
          {member.module && <span className="label ml-3 font-sans font-normal">{humanize(member.module)}</span>}
        </h2>
        <p role="status">
          {link === 'lost' ? (
            <span className="text-warn">Connection lost. Reconnecting.</span>
          ) : link === 'connecting' ? (
            <span className="text-muted-foreground">Connecting.</span>
          ) : status ? (
            <StatusMark playbook={playbook} severity={top?.severity} />
          ) : (
            <span className="text-muted-foreground">{newest ? 'No playbook active' : 'Nothing received yet'}</span>
          )}
        </p>
      </div>
      <p className="mt-1 text-muted-foreground">
        {newest ? `Data up to ${clock.format(newest)} UTC.` : 'No shared data has reached Earth yet.'}
        {delayS !== null && ` Comm delay ${mmss(delayS)}${fixed === null ? ', the light time from Mars' : ''}.`}
      </p>
      {withheld.length > 0 && (
        <p className="text-muted-foreground">
          Kept private by {name}: {withheld.map((k) => label(...(k.split('/', 2) as [string, string]))).join(', ')}.
        </p>
      )}

      {status && status.alerts.length > 0 && (
        <ul className="mt-2">
          {status.alerts.map((a) => (
            <li key={a.id} className="border-b py-3">
              <StatusMark playbook={playbook} severity={a.severity} className="mr-3" />
              {a.message} <span className="text-muted-foreground">Since {clock.format(a.ts)} UTC.</span>
              {edgeActions(a, playbook) && <span className="block text-muted-foreground">{edgeActions(a, playbook)}</span>}
            </li>
          ))}
        </ul>
      )}

      {status && status.forecasts.length > 0 && (
        <div className="mt-6 grid gap-6 @xl:grid-cols-2 @4xl:grid-cols-3">
          {status.forecasts.map((f) => (
            <ForecastChart
              key={f.rule}
              forecast={f}
              label={label(f.domain, f.metric)}
              unit={playbook?.domains[f.domain]?.indicators[f.metric]?.unit}
              missionStart={playbook?.mission?.start}
            />
          ))}
        </div>
      )}

      {domains.length > 0 && (
        <div className="mt-6 gap-6 space-y-6 @xl:columns-2 @4xl:columns-3">
          {domains.map((d) => (
            <DomainPanel key={d} scope={id} domain={d} readings={byDomain.get(d)!} playbook={playbook} status={status} />
          ))}
        </div>
      )}
    </section>
  )
}

/** Earth side: the edge's decisions to review first, then each crew member's shared data one comm delay late, then the black box. */
export function MissionControl({ crew, playbook, delayS, earth = false, onPlaybook }: Props) {
  const [version, setVersion] = useState(0)
  const bump = useCallback(() => setVersion((v) => v + 1), [])
  return (
    <div className="space-y-12">
      {/* The demo page has its own title and playbook control. */}
      {!earth && (
        <div className="flex flex-wrap items-end justify-between gap-x-10 gap-y-4">
          <div>
            <h1 className="display text-2xl">Mission control</h1>
            <p className="mt-2 max-w-prose text-muted-foreground">
              What Earth has received. The edge guided the crew before any of it arrived.
            </p>
          </div>
          {onPlaybook && <PlaybookSwitcher onSwitched={onPlaybook} />}
        </div>
      )}
      <HabitatMap />
      <ReviewQueue onReviewed={bump} version={version} earth={earth} />
      {!crew && <p role="status">Loading the crew list.</p>}
      {crew && crew.length === 0 && <p role="status">No crew members have reported yet.</p>}
      {crew?.map((c) => <CrewCard key={c.entity_id} member={c} playbook={playbook} delayS={delayS} onLedger={bump} />)}
      <BlackBox version={version} earth={earth} controls={earth ? 'all' : 'verify'} />
      <UnderTheHood />
    </div>
  )
}
