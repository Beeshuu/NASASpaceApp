import { useCallback, useEffect, useState } from 'react'
import { Button } from '@/components/ui/button'
import { type LedgerEntry, short, TYPE_LABELS, when } from '@/lib/ledger'
import { humanize } from '@/lib/playbook'

/** What the edge decided that mission control has not reviewed yet. A review is a new log entry; nothing is edited. */
type Props = {
  onReviewed: () => void
  /** Bumped by the parent when new entries may be there, so the queue reloads at once. */
  version?: number
  /** Only entries that have reached Earth. */
  earth?: boolean
}

export function ReviewQueue({ onReviewed, version = 0, earth = false }: Props) {
  const [queue, setQueue] = useState<LedgerEntry[] | null>(null)
  const [notes, setNotes] = useState<Record<number, string>>({})
  const [problem, setProblem] = useState<string | null>(null)
  const [overriding, setOverriding] = useState<number | null>(null) // the entry whose override note is open

  const load = useCallback(async () => {
    try {
      const res = await fetch(`/api/ledger/queue${earth ? '?earth=1' : ''}`)
      if (!res.ok) throw new Error(String(res.status))
      setQueue(await res.json())
    } catch {
      setProblem('The review queue did not load. Trying again every 10 seconds.')
    }
  }, [earth])

  useEffect(() => {
    load()
    const timer = window.setInterval(load, 10_000)
    return () => window.clearInterval(timer)
  }, [load, version])

  const review = async (seq: number, decision: 'approve' | 'override') => {
    try {
      const res = await fetch(`/api/ledger/review/${seq}`, {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify({ decision, note: notes[seq] ?? '' }),
      })
      if (!res.ok) return setProblem((await res.json()).detail ?? 'The review was not saved.')
      setProblem(null)
      setOverriding(null)
      await load()
      onReviewed()
    } catch {
      setProblem('The review was not saved. Check the connection and try again.')
    }
  }

  return (
    <section aria-labelledby="review-queue" className="sec">
      <h2 id="review-queue" className="sec-title">
        Waiting for review {queue && queue.length > 0 && `(${queue.length})`}
      </h2>
      <p role="status" className="text-warn">
        {problem}
      </p>
      {queue && queue.length === 0 && <p className="mt-2">Nothing to review.</p>}
      {queue && queue.length > 0 && (
        <ul className="mt-2">
          {queue.map((e) => {
            const noteId = `note-${e.seq}`
            const note = notes[e.seq] ?? ''
            return (
              <li key={e.seq} className="border-b py-3">
                <div className="flex flex-wrap items-center justify-between gap-x-6 gap-y-3">
                  <div className="min-w-0 flex-1 basis-80">
                    <p className="label">
                      <span className="font-bold text-foreground">{TYPE_LABELS[e.type] ?? e.type}</span>
                      {e.entity_id && ` · ${humanize(e.entity_id)}`} · {when(e.timestamp)} · #{e.seq} {short(e.hash)}
                    </p>
                    <p className="mt-1">{e.summary}</p>
                  </div>
                  {overriding !== e.seq && (
                    <div className="flex gap-2">
                      <Button onClick={() => review(e.seq, 'approve')}>Approve</Button>
                      <Button variant="outline" aria-expanded={false} onClick={() => setOverriding(e.seq)}>
                        Override
                      </Button>
                    </div>
                  )}
                </div>
                {overriding === e.seq && (
                  <div className="mt-3 flex flex-wrap items-end gap-2">
                    <label htmlFor={noteId} className="basis-full text-sm">
                      What to do instead
                    </label>
                    <input
                      id={noteId}
                      autoFocus
                      value={note}
                      maxLength={500}
                      onChange={(ev) => setNotes({ ...notes, [e.seq]: ev.target.value })}
                      className="field min-w-0 flex-1 basis-60"
                    />
                    <Button disabled={!note.trim()} onClick={() => review(e.seq, 'override')}>
                      Save override
                    </Button>
                    <Button variant="ghost" onClick={() => setOverriding(null)}>
                      Cancel
                    </Button>
                  </div>
                )}
              </li>
            )
          })}
        </ul>
      )}
    </section>
  )
}
