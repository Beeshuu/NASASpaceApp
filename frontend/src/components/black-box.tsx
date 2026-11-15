import { useCallback, useEffect, useState } from 'react'
import { Button } from '@/components/ui/button'
import { type LedgerEntry, short, TYPE_LABELS, when } from '@/lib/ledger'
import { humanize } from '@/lib/playbook'

type Verify = {
  ok: boolean
  checked: number
  first_bad_seq: number | null
  reason: string | null
  complete: boolean
  from_seq: number
  to_seq: number
}

type Props = {
  /** Only this crew member's entries and the mission-wide ones. Omit for every entry. */
  entityId?: string
  /** Bumped by the parent after a review, so the list reloads at once. */
  version?: number
  /** Only entries that have reached Earth. */
  earth?: boolean
  /** none: crew view, a collapsed read-only log. verify: mission control. all: the demo, with tamper and restore. */
  controls?: 'none' | 'verify' | 'all'
}

/** The black-box decision log: newest entries, each linked to the one before it by hash, and a chain check. */
export function BlackBox({ entityId, version = 0, earth = false, controls = 'verify' }: Props) {
  const [entries, setEntries] = useState<LedgerEntry[] | null>(null)
  const [demo, setDemo] = useState(false)
  const [failed, setFailed] = useState(false)
  const [verify, setVerify] = useState<Verify | 'running' | 'failed' | null>(null)
  const [demoNote, setDemoNote] = useState<string | null>(null)

  const load = useCallback(async () => {
    try {
      const res = await fetch(
        `/api/ledger?limit=8${entityId ? `&entity_id=${encodeURIComponent(entityId)}` : ''}${earth ? '&earth=1' : ''}`,
      )
      if (!res.ok) throw new Error(String(res.status))
      const body = await res.json()
      setEntries(body.entries)
      setDemo(body.demo)
      setFailed(false)
    } catch {
      setFailed(true)
    }
  }, [entityId, earth])

  useEffect(() => {
    load()
    const timer = window.setInterval(load, 10_000)
    return () => window.clearInterval(timer)
  }, [load, version])

  const runVerify = async () => {
    setVerify('running')
    try {
      const res = await fetch('/api/ledger/verify')
      setVerify(res.ok ? await res.json() : 'failed')
    } catch {
      setVerify('failed')
    }
  }

  const demoAction = async (path: 'tamper' | 'restore') => {
    try {
      const res = await fetch(`/api/ledger/demo/${path}`, {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: '{}',
      })
      const body = await res.json()
      if (!res.ok) return setDemoNote(body.detail ?? 'That did not work.')
      setDemoNote(
        path === 'tamper'
          ? body.locked
            ? `R2 refused the delete and the overwrite of entry #${body.tampered}: Bucket Lock holds everything under ledger/ forever. ` +
              'To show what verify would catch, the edited entry went to a separate demo-only copy, which verify now reads.'
            : `No R2 lock rule here (local dev?): the edit was not refused. Entry #${body.tampered} was edited in a demo-only copy.`
          : body.restored.length
            ? `Dropped the demo-only copy of ${body.restored.map((s: number) => `#${s}`).join(', ')}. Verify reads the locked originals again.`
            : 'Nothing was tampered with.',
      )
      await runVerify()
    } catch {
      setDemoNote('The server did not answer.')
    }
  }

  const list = entries && entries.length > 0 && (
    <ol className="mt-2">
      {entries.map((e) => (
        <li key={e.seq} className="border-b py-3">
          <p className="label">
            <span className="font-bold text-foreground">{TYPE_LABELS[e.type] ?? e.type}</span>
            {e.entity_id && ` · ${humanize(e.entity_id)}`} · {when(e.timestamp)}
          </p>
          <p className="mt-1">{e.summary}</p>
          {controls !== 'none' && (
            <p className="mt-1 text-sm text-muted-foreground">
              #{e.seq} {short(e.hash)}{' '}
              <span className="sr-only">{e.seq === 0 ? 'first entry, no previous hash' : `links to entry ${e.seq - 1}`}</span>
              <span aria-hidden>← {e.seq === 0 ? 'start' : `#${e.seq - 1} ${short(e.prev_hash)}`}</span>
            </p>
          )}
        </li>
      ))}
    </ol>
  )

  return (
    <section aria-labelledby="black-box" className="sec">
      <h2 id="black-box" className="sec-title">
        Black box
      </h2>
      {failed && <p className="mt-2 text-warn">The log did not load. Trying again every 10 seconds.</p>}
      {entries && entries.length === 0 && <p className="mt-2">Nothing logged yet.</p>}

      {controls === 'none' ? (
        // Crew view: the log is one tap away, never in the way of the readings.
        list && (
          <details>
            <summary className="flex min-h-11 items-center justify-between gap-3">
              <span>Every alert, step and answer here is logged. Latest {entries!.length} entries</span>
              <span className="chevron" />
            </summary>
            {list}
          </details>
        )
      ) : (
        <>
          <p className="mt-2 max-w-prose text-muted-foreground">
            Each entry carries the hash of the one before it, so an edit anywhere breaks the chain.
          </p>
          <div className="mt-3 flex flex-wrap items-center gap-2">
            <Button variant="outline" onClick={runVerify} disabled={verify === 'running'}>
              {verify === 'running' ? 'Verifying' : 'Verify chain'}
            </Button>
            {demo && controls === 'all' && (
              <>
                <Button variant="outline" onClick={() => demoAction('tamper')}>
                  Tamper with newest
                </Button>
                <Button variant="outline" onClick={() => demoAction('restore')}>
                  Restore
                </Button>
              </>
            )}
          </div>
          <div role="status" className="mt-3">
            {verify === 'failed' && <p className="text-warn">The check did not run. Try again.</p>}
            {verify && typeof verify === 'object' &&
              (verify.ok ? (
                <p className="font-bold">
                  Chain verified: {verify.checked} {verify.checked === 1 ? 'entry' : 'entries'}, every hash and link checks
                  out{verify.complete ? '.' : `, the newest ones (#${verify.from_seq} to #${verify.to_seq}).`}
                </p>
              ) : (
                <p className="font-bold text-destructive">Chain broken: {verify.reason}.</p>
              ))}
            {demoNote && <p className="text-muted-foreground">{demoNote}</p>}
          </div>
          {list}
        </>
      )}
    </section>
  )
}
