import type { useSharing } from '@/hooks/use-sharing'
import { humanize, type Playbook } from '@/lib/playbook'

type Props = { sharing: ReturnType<typeof useSharing>; playbook: Playbook | null }

/** The crew member decides what mission control sees. Safety-critical indicators are fixed by the playbook. */
export function SharingPanel({ sharing, playbook }: Props) {
  const { rows, busy, problem, setShared, setCheckinShared } = sharing
  const label = (d: string, m: string) => playbook?.domains[d]?.indicators[m]?.label ?? humanize(m)
  const choosable = rows?.filter((r) => r.privacy !== 'always_shared') ?? []
  const fixed = rows?.filter((r) => r.privacy === 'always_shared') ?? []
  const shared = choosable.filter((r) => r.shared).length
  // The check-in's number fields; its free-text answers are never sent.
  const fed = (playbook?.checkin?.fields ?? []).filter((f) => f.domain && f.metric)
  const checkinRows = choosable.filter((r) => fed.some((f) => f.domain === r.domain && f.metric === r.metric))
  const checkinShared = checkinRows.length > 0 && checkinRows.every((r) => r.shared)

  return (
    <section aria-labelledby="sharing" className="sec">
      <h2 id="sharing" className="sec-title">
        What mission control sees
      </h2>
      <p role="status" className="text-warn">
        {problem}
      </p>
      {!rows && !problem && <p className="mt-2">Loading your sharing choices.</p>}
      {rows && rows.length === 0 && <p className="mt-2">No playbook is active, so there is nothing to choose yet.</p>}
      {choosable.length > 0 && (
        // Closed by default: one line says where things stand, the switches are one tap away.
        <details className="mt-1">
          <summary className="flex min-h-11 items-center justify-between gap-3">
            <span>
              {shared} shared, {choosable.length - shared} only you
            </span>
            <span className="chevron" />
          </summary>
          {checkinRows.length > 0 && (
            <button
              type="button"
              disabled={busy !== null}
              onClick={() => setCheckinShared(!checkinShared)}
              className="min-h-11 w-full py-2 text-left underline disabled:opacity-50"
            >
              {busy === 'checkin' ? 'Saving' : checkinShared ? 'Stop sharing my daily check-in' : 'Share my daily check-in with the flight surgeon'}
            </button>
          )}
          <ul>
            {choosable.map((r) => {
              const key = `${r.domain}/${r.metric}`
              return (
                <li key={key} className="border-t">
                  <button
                    type="button"
                    role="switch"
                    aria-checked={r.shared}
                    disabled={busy !== null}
                    onClick={() => setShared(r.domain, r.metric, !r.shared)}
                    className="group flex min-h-11 w-full items-center justify-between gap-3 py-2 text-left disabled:opacity-50"
                  >
                    <span>
                      {label(r.domain, r.metric)}
                      <span className="block text-sm text-muted-foreground">
                        {busy === key ? 'Saving' : r.shared ? 'Shared' : 'Only you'}
                      </span>
                    </span>
                    <span className="flex h-6 w-11 shrink-0 items-center rounded-full border border-input p-0.5 group-aria-checked:border-primary group-aria-checked:bg-primary">
                      <span className="size-4 rounded-full bg-muted-foreground group-aria-checked:translate-x-5 group-aria-checked:bg-primary-foreground motion-safe:transition-transform" />
                    </span>
                  </button>
                </li>
              )
            })}
          </ul>
          <p className="mt-2 text-sm text-muted-foreground">
            Private readings and their alerts stay with you until you share them. Every change is logged.
          </p>
        </details>
      )}
      {fixed.length > 0 && (
        <p className="mt-2 text-sm text-muted-foreground">
          Always shared, for safety: {fixed.map((r) => label(r.domain, r.metric)).join(', ')}.
        </p>
      )}
    </section>
  )
}
