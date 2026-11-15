import { StatusMark } from '@/components/status-mark'
import { Ticker } from '@/components/ticker'
import { type Alert, type Reading, readingKey, type Status } from '@/hooks/use-live-readings'
import { humanize, type Playbook } from '@/lib/playbook'

/** No more digits than the eye can use: 142, 36.8, 0.65. */
const format = (n: number) =>
  n.toLocaleString('en', { maximumFractionDigits: Math.abs(n) >= 100 ? 0 : Math.abs(n) >= 10 ? 1 : 2 })

/** "+38% vs usual", or null when there is no baseline to compare with. */
function versusUsual(value: number, baseline: number | undefined) {
  if (baseline === undefined || baseline === 0) return null
  const pct = Math.round(((value - baseline) / Math.abs(baseline)) * 100)
  if (pct === 0) return 'at your usual'
  return `${pct > 0 ? '+' : '−'}${Math.abs(pct)}% vs usual`
}

type Props = {
  /** Whose panel this is, so ids stay unique when several crew members share a page. */
  scope: string
  domain: string
  readings: Reading[]
  playbook: Playbook | null
  status: Status | null
}

export function DomainPanel({ scope, domain, readings, playbook, status }: Props) {
  const spec = playbook?.domains[domain]
  const severity = status?.domains[domain]
  const id = `domain-${scope}-${domain}`
  const alertFor = (metric: string): Alert | undefined =>
    status?.alerts.find((a) => a.domain === domain && a.metric === metric)

  return (
    <section aria-labelledby={id} className="sec break-inside-avoid">
      <div className="flex items-center justify-between gap-4">
        <h2 id={id} className="sec-title">
          {spec?.label ?? humanize(domain)}
        </h2>
        {/* Only domains the playbook covers get a verdict. */}
        {status && spec && <StatusMark playbook={playbook} severity={severity} />}
      </div>
      {/* gap-px over the hairline colour draws the instrument grid */}
      <dl className="mt-3 grid grid-cols-2 gap-px border bg-border">
        {readings.map((r, i) => {
          const indicator = spec?.indicators[r.metric]
          const alert = alertFor(r.metric)
          const unit = indicator?.unit ?? r.unit
          const delta = versusUsual(r.value, status?.baselines[readingKey(r)])
          const wide = i === readings.length - 1 && readings.length % 2 === 1
          return (
            <div key={r.metric} className={`flex flex-col bg-background p-3 ${wide ? 'col-span-2' : ''}`}>
              <dt className="label">{indicator?.label ?? humanize(r.metric)}</dt>
              <dd className="mt-auto pt-3">
                <span className="readout text-2xl">
                  <Ticker value={r.value} format={format} />
                </span>
                {unit && <span className="ml-2 text-sm text-muted-foreground">{unit}</span>}
                {alert ? (
                  <StatusMark playbook={playbook} severity={alert.severity} className="mt-2 flex" />
                ) : (
                  delta && <span className="mt-1 block text-sm text-muted-foreground">{delta}</span>
                )}
                {indicator?.note && <span className="mt-1 block text-sm text-muted-foreground">{indicator.note}</span>}
              </dd>
            </div>
          )
        })}
      </dl>
    </section>
  )
}
