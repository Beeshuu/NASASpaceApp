import { type FormEvent, useState } from 'react'
import { Button } from '@/components/ui/button'
import type { Alert } from '@/hooks/use-live-readings'

type Answer = { answer: string; sources: string[] }

type Props = { entityId: string; role: string; alert: Alert | undefined }

/** The playbook's assistant. It explains an alert, walks through the checklist and says when to call someone. It never diagnoses. */
export function FlightSurgeon({ entityId, role, alert }: Props) {
  const [question, setQuestion] = useState('')
  const [asked, setAsked] = useState('') // what the answer on screen responds to
  const [answer, setAnswer] = useState<Answer | null>(null)
  const [problem, setProblem] = useState('')
  const [busy, setBusy] = useState(false)

  const ask = async (body: { alert_id?: string; question?: string }, label: string) => {
    setBusy(true)
    setProblem('')
    try {
      const res = await fetch(`/api/astronauts/${encodeURIComponent(entityId)}/explain`, {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify(body),
      })
      if (res.status === 429) throw new Error('Wait a few seconds, then ask again.')
      if (res.status === 404) throw new Error('That alert has cleared. Ask a question instead.')
      if (!res.ok) throw new Error('The assistant did not answer. Follow the checklist, and ask again in a moment.')
      setAnswer(await res.json())
      setAsked(label)
      setQuestion('')
    } catch (e) {
      setProblem(e instanceof TypeError ? 'No connection to the assistant. Follow the checklist, and ask again in a moment.' : (e as Error).message)
    } finally {
      setBusy(false)
    }
  }

  const submit = (e: FormEvent) => {
    e.preventDefault()
    const text = question.trim()
    if (!text) return setProblem('Type a question first.')
    // The top alert goes along as context, so "is this dangerous?" has something to refer to.
    ask({ question: text, alert_id: alert?.id }, text)
  }

  return (
    <section aria-labelledby="assistant-title" className="sec">
      <h2 id="assistant-title" className="sec-title">
        {role}
      </h2>
      <p className="mt-2 text-muted-foreground">Explains readings. It does not diagnose.</p>

      {alert && (
        <Button variant="outline" className="mt-3" disabled={busy} onClick={() => ask({ alert_id: alert.id }, alert.message)}>
          Explain this alert
        </Button>
      )}

      <details className="mt-1">
        <summary className="flex min-h-11 items-center justify-between gap-3">
          <label htmlFor="assistant-question" className="cursor-pointer">Ask about your readings</label>
          <span className="chevron" />
        </summary>
      <form onSubmit={submit}>
        <textarea
          id="assistant-question"
          rows={2}
          maxLength={500}
          value={question}
          onChange={(e) => setQuestion(e.target.value)}
          className="field w-full py-2"
        />
        <Button type="submit" variant="outline" className="mt-2 min-h-11 px-4" disabled={busy}>
          Send question
        </Button>
      </form>
      </details>

      <div role="status" className="mt-3">
        {busy && <p>Writing an answer.</p>}
        {problem && <p className="text-warn">{problem}</p>}
        {answer && !busy && (
          <>
            <p className="text-sm text-muted-foreground">In answer to: {asked}</p>
            <p className="mt-1 whitespace-pre-line">{answer.answer}</p>
            <p className="mt-2 text-sm text-muted-foreground">
              {answer.sources.length > 0
                ? `Drawn from the playbook guidance: ${answer.sources.join('; ')}.`
                : 'No playbook guidance matched this, so the answer rests on the alert and checklist alone.'}
            </p>
          </>
        )}
      </div>
    </section>
  )
}
