import { motion } from 'motion/react'
import { AlertChecklist } from '@/components/alert-checklist'
import { DailyCheckin } from '@/components/daily-checkin'
import { DomainPanel } from '@/components/domain-panel'
import { EarthLink } from '@/components/earth-link'
import { IncidentStatus } from '@/components/incident-status'
import { FlightSurgeon } from '@/components/flight-surgeon'
import { ForecastChart } from '@/components/forecast-chart'
import { TrendCharts } from '@/components/trend-charts'
import { SharingPanel } from '@/components/sharing-panel'
import { StatusMark } from '@/components/status-mark'
import { Skeleton } from '@/components/ui/skeleton'
import { useChecklists } from '@/hooks/use-checklists'
import { useSharing } from '@/hooks/use-sharing'
import { type Alert, type Link, type Status, useLiveReadings } from '@/hooks/use-live-readings'
import { clock, forecastTime, heldActions, humanize, type Playbook, severityLabel } from '@/lib/playbook'

/** A forecast alert says when the twin expects the crossing. Any other alert says when it began. */
const when = (a: Alert) =>
  a.eta && a.eta > a.ts ? `Forecast for ${forecastTime(a.eta, a.ts)}.` : `Since ${clock.format(a.ts)} UTC.`

type Summary = { tag?: string; tone?: string; headline: string; detail?: string }

/** The one sentence the crew member reads first. A lost connection outranks everything: stale data must not look current. */
function summarize(link: Link, count: number, status: Status | null, playbook: Playbook | null): Summary {
  if (link === 'lost')
    return {
      tone: 'text-warn',
      headline: 'Connection lost.',
      detail:
        count > 0
          ? 'These are the last values received. Reconnecting now.'
          : 'No values were received before the connection dropped. Reconnecting now.',
    }
  if (link === 'connecting') return { headline: 'Connecting to your health record.' }
  if (count === 0)
    return {
      headline: 'Connected. No readings received yet.',
      detail: 'Each sensor shows up here as soon as it sends its first value.',
    }
  if (!status)
    return {
      headline: 'Your readings are live.',
      detail: 'No playbook is active, so nothing is checking these values yet.',
    }
  const top = status.alerts[0]
  if (top)
    return {
      tag: severityLabel(playbook, top.severity),
      headline: top.message,
      detail: top.queued?.length ? `${when(top)} Sent to Earth for review: ${heldActions(playbook, top.queued)}.` : when(top),
    }
  const learning = status.learning.length
  return {
    headline: 'All checked readings are in range.',
    detail:
      learning > 0
        ? `Still learning your usual range for ${learning} of your readings. Those are not compared with it yet.`
        : undefined,
  }
}

type Props = { entityId: string; name: string; playbook: Playbook | null; delayS: number | null }

export function MyHealth({ entityId, name, playbook, delayS }: Props) {
  const { readings, status, link, earthLink } = useLiveReadings(entityId)
  const summary = summarize(link, readings.length, status, playbook)
  const alerts = link === 'live' ? (status?.alerts ?? []) : []
  const others = alerts.slice(1)
  const checklists = useChecklists(entityId)
  const sharing = useSharing(entityId)
  // An alert on a private reading the crew member has not shared never reaches Earth. Say so where it shows.
  const onlyYou = (a: Alert | undefined) =>
    a &&
    playbook?.domains[a.domain]?.indicators[a.metric]?.privacy === 'private' &&
    !sharing.isShared(a.domain, a.metric) ? (
      <p className="mt-2 font-bold">Only you can see this alert. Share it under "What mission control sees" to get help from Earth.</p>
    ) : null

  const checklistFor = (alert: Alert | undefined, open: boolean) => {
    const checklist = alert?.checklist && playbook?.checklists[alert.checklist]
    if (!alert || !checklist) return null
    const alertId = `${entityId}:${alert.id}` // the id the alert is stored under
    return (
      <AlertChecklist
        key={alertId}
        checklist={checklist}
        done={checklists.done[alertId] ?? []}
        failed={checklists.failed === alertId}
        open={open}
        onDone={(step) => checklists.markDone(alertId, step)}
      />
    )
  }

  const byDomain = Map.groupBy(
    readings.toSorted((a, b) => a.metric.localeCompare(b.metric)),
    (r) => r.domain,
  )
  // Playbook order first, then anything the playbook does not know.
  const known = Object.keys(playbook?.domains ?? {}).filter((d) => byDomain.has(d))
  const domains = [...known, ...[...byDomain.keys()].filter((d) => !known.includes(d)).sort()]
  const newest = readings.reduce((max, r) => Math.max(max, r.ts), 0)

  return (
    <>
      <h1 className="sr-only">My Health: {name}</h1>
      <div className="max-w-[46rem]">
        {/* A new headline arrives with a short rise, so the eye catches that the status changed. */}
        <motion.div key={summary.headline} role="status" initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.25, ease: 'easeOut' }}>
          {summary.tag && <StatusMark playbook={playbook} severity={alerts[0]?.severity} />}
          <p className={`mt-2 text-2xl leading-tight font-bold text-balance sm:text-3xl ${summary.tone ?? ''}`}>
            {summary.headline}
          </p>
          {summary.detail && <p className="mt-2 text-muted-foreground">{summary.detail}</p>}
          {onlyYou(alerts[0])}
        </motion.div>
        {/* The worst alert's checklist is open already: the crew member should not have to look for it. */}
        {checklistFor(alerts[0], true)}

        {others.length > 0 && (
          <section aria-labelledby="also" className="sec mt-6">
            <h2 id="also" className="sec-title">
              Also needs your attention
            </h2>
            <ul className="mt-2">
              {others.map((a) => (
                <motion.li key={a.id} initial={{ opacity: 0, x: -8 }} animate={{ opacity: 1, x: 0 }} transition={{ duration: 0.25, ease: 'easeOut' }} className="border-b py-3">
                  <StatusMark playbook={playbook} severity={a.severity} className="mr-3" />
                  {a.message} <span className="text-muted-foreground">{when(a)}</span>
                  {a.queued?.length ? (
                    <span className="block text-muted-foreground">Sent to Earth for review: {heldActions(playbook, a.queued)}.</span>
                  ) : null}
                  {onlyYou(a)}
                  {checklistFor(a, false)}
                </motion.li>
              ))}
            </ul>
          </section>
        )}

        <IncidentStatus entityId={entityId} />

        {link === 'live' && status?.crew_alerts?.length ? (
          <section aria-labelledby="crew-alerts" className="sec mt-6">
            <h2 id="crew-alerts" className="sec-title">
              From your crew
            </h2>
            <ul className="mt-2">
              {status.crew_alerts.map((c) => (
                <li key={c.key} className="border-b py-3">
                  <StatusMark playbook={playbook} severity={c.severity} className="mr-3" />
                  <span className="font-bold">
                    {c.prewarn ? 'Pre-warned by ' : ''}{humanize(c.from)}, {c.scope === 'all' ? 'whole crew' : 'your module'}:
                  </span>{' '}
                  {c.message} <span className="text-muted-foreground">Since {clock.format(c.ts)} UTC.</span>
                </li>
              ))}
            </ul>
          </section>
        ) : null}

        {newest > 0 && (
          <p className="label mt-4">
            Newest reading <time dateTime={new Date(newest).toISOString()}>{clock.format(newest)} UTC</time>
          </p>
        )}
        {link === 'live' && newest > 0 && <EarthLink delayS={delayS} missionNow={newest} link={earthLink} />}
      </div>

      {/* The readings are the instrument: they come straight after the status, before anything optional. */}
      {link === 'connecting' && readings.length === 0 ? (
        <div aria-hidden className="mt-12 grid gap-6 @xl:grid-cols-2 @4xl:grid-cols-3">
          {[4, 2, 3].map((rows, i) => (
            <div key={i} className="sec space-y-3">
              <Skeleton className="h-4 w-40" />
              {Array.from({ length: rows }, (_, j) => (
                <Skeleton key={j} className="h-10" />
              ))}
            </div>
          ))}
        </div>
      ) : (
        <div className="mt-12 gap-6 space-y-6 @xl:columns-2 @4xl:columns-3">
          {domains.map((domain) => (
            <DomainPanel
              key={domain}
              scope={entityId}
              domain={domain}
              readings={byDomain.get(domain)!}
              playbook={playbook}
              status={status}
            />
          ))}
        </div>
      )}

      {status && status.forecasts.length > 0 && (
        <section aria-labelledby="twin" className="mt-12">
          <h2 id="twin" className="sec-title">
            Where your trends are heading
          </h2>
          <div className="mt-4 grid gap-6 @xl:grid-cols-2 @4xl:grid-cols-3">
            {status.forecasts.map((f) => {
              const spec = playbook?.domains[f.domain]?.indicators[f.metric]
              return (
                <ForecastChart
                  key={f.rule}
                  forecast={f}
                  label={spec?.label ?? humanize(f.metric)}
                  unit={spec?.unit}
                  missionStart={playbook?.mission?.start}
                />
              )
            })}
          </div>
        </section>
      )}

      {readings.length > 0 && <TrendCharts entityId={entityId} playbook={playbook} />}

      {readings.length > 0 && (
        <div className="mt-12 grid items-start gap-6 @xl:grid-cols-2 @4xl:grid-cols-3">
          {playbook?.checkin && <DailyCheckin entityId={entityId} checkin={playbook.checkin} missionNow={newest} />}
          {playbook?.ai && <FlightSurgeon entityId={entityId} role={playbook.ai.role} alert={alerts[0]} />}
          <SharingPanel sharing={sharing} playbook={playbook} />
        </div>
      )}
    </>
  )
}
