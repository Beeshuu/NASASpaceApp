import { type FormEvent, useEffect, useState } from 'react'
import { ReactionTest } from '@/components/reaction-test'
import { Button } from '@/components/ui/button'
import type { CheckinField, Playbook } from '@/lib/playbook'

type Answers = Record<string, number | string>

const utcDay = (ts: number) => new Date(ts).toISOString().slice(0, 10)
const input = 'field w-full'

function Field({ field, value, set }: { field: CheckinField; value: number | string | undefined; set: (v: number | string | undefined) => void }) {
  const id = `checkin-${field.id}`
  if (field.kind === 'scale') {
    const options = Array.from({ length: field.max! - field.min! + 1 }, (_, i) => field.min! + i)
    return (
      <fieldset>
        <legend className="font-bold">{field.question}</legend>
        <div className="mt-2 flex gap-2">
          {options.map((n) => (
            <label
              key={n}
              className="flex min-h-11 flex-1 cursor-pointer items-center justify-center rounded-sm border border-input text-lg has-checked:border-primary has-checked:bg-primary has-checked:text-primary-foreground has-focus-visible:outline-2 has-focus-visible:outline-offset-2 has-focus-visible:outline-primary"
            >
              <input type="radio" name={id} className="sr-only" checked={value === n} onChange={() => set(n)} />
              {n}
            </label>
          ))}
        </div>
        <p className="mt-1 flex justify-between text-sm text-muted-foreground">
          <span>
            {field.min}: {field.low_label}
          </span>
          <span>
            {field.max}: {field.high_label}
          </span>
        </p>
      </fieldset>
    )
  }
  if (field.kind === 'reaction_test')
    return (
      <div>
        <p className="font-bold">{field.question}</p>
        <ReactionTest onResult={(ms) => set(ms ?? undefined)} />
      </div>
    )
  return (
    <div>
      <label htmlFor={id} className="font-bold">
        {field.question}
      </label>
      {field.kind === 'number' ? (
        <input
          id={id}
          type="number"
          inputMode="decimal"
          min={field.min ?? undefined}
          max={field.max ?? undefined}
          step={field.step ?? 'any'}
          value={value ?? ''}
          onChange={(e) => set(e.target.value === '' ? undefined : Number(e.target.value))}
          className={`${input} mt-2 font-mono`}
        />
      ) : (
        <textarea id={id} rows={2} maxLength={1000} value={value ?? ''} onChange={(e) => set(e.target.value)} className={`${input} mt-2 py-2`} />
      )}
    </div>
  )
}

type Props = { entityId: string; checkin: NonNullable<Playbook['checkin']>; missionNow: number }

/** The daily check-in from the playbook. Answers become readings, so the same rules and baselines apply to them. */
export function DailyCheckin({ entityId, checkin, missionNow }: Props) {
  const url = `/api/astronauts/${encodeURIComponent(entityId)}/checkin`
  const [lastTs, setLastTs] = useState<number | null>(null)
  const [due, setDue] = useState(false) // the daily reminder has gone out and no check-in has been saved since
  const [open, setOpen] = useState(false)
  const [answers, setAnswers] = useState<Answers>({})
  const [error, setError] = useState('')
  const [saving, setSaving] = useState(false)

  useEffect(() => {
    fetch(url)
      .then((r) => (r.ok ? r.json() : { ts: null }))
      .then((d) => {
        setLastTs(d.ts)
        setDue(Boolean(d.due))
      })
      .catch(() => {}) // unknown counts as not done, so the crew member is asked rather than skipped
  }, [url])

  const doneToday = lastTs !== null && utcDay(lastTs) === utcDay(missionNow || Date.now())

  const submit = async (e: FormEvent) => {
    e.preventDefault()
    const missing = checkin.fields.filter((f) => f.kind !== 'text' && typeof answers[f.id] !== 'number')
    if (missing.length > 0) return setError(`Still to answer: ${missing.map((f) => f.question).join(' ')}`)
    setSaving(true)
    setError('')
    try {
      const res = await fetch(url, {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify({ answers }),
      })
      if (!res.ok) throw new Error((await res.json()).detail ?? String(res.status))
      setLastTs((await res.json()).ts)
      setDue(false)
      setOpen(false)
      setAnswers({})
    } catch (err) {
      setError(`The check-in was not saved (${err instanceof Error ? err.message : 'no connection'}). Your answers are still here. Save again.`)
    } finally {
      setSaving(false)
    }
  }

  return (
    <section aria-labelledby="checkin-title" className="sec">
      <h2 id="checkin-title" className="sec-title">
        {checkin.title}
      </h2>
      {!open ? (
        <>
          <p role="status" className="mt-2">
            {doneToday ? 'Done today.' : `${due ? 'Reminder: your daily check-in is due. ' : ''}Not done today. It takes about a minute.`}
          </p>
          <Button variant="outline" className="mt-3" onClick={() => setOpen(true)}>
            {doneToday ? 'Check in again' : 'Start today’s check-in'}
          </Button>
        </>
      ) : (
        <form onSubmit={submit} noValidate className="mt-3 space-y-6">
          {checkin.fields.map((f) => (
            <Field key={f.id} field={f} value={answers[f.id]} set={(v) => (setError(''), setAnswers(({ [f.id]: _, ...rest }) => (v === undefined ? rest : { ...rest, [f.id]: v })))} />
          ))}
          <p role="alert" className="text-warn">
            {error}
          </p>
          <div className="flex flex-wrap gap-2">
            <Button type="submit" className="min-h-11 px-4" disabled={saving}>
              {saving ? 'Saving' : 'Save check-in'}
            </Button>
            <Button type="button" variant="ghost" className="min-h-11 px-4" onClick={() => setOpen(false)}>
              Close without saving
            </Button>
          </div>
        </form>
      )}
    </section>
  )
}
