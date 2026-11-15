/** The parts of the active playbook the frontend reads. Labels and severities come from here, never from code. */
export type Playbook = {
  name: string
  version: number
  severities: { id: string; label: string }[] // lowest to highest
  domains: Record<string, { label: string; indicators: Record<string, Indicator> }>
  checklists: Record<string, Checklist>
  checkin: { title: string; fields: CheckinField[] } | null
  mission: { start: string } | null
  ai: { role: string } | null
}

export type Privacy = 'private' | 'shared' | 'always_shared'
export type Indicator = { label: string; unit?: string | null; note?: string | null; privacy: Privacy }

export type Checklist = { title: string; steps: string[] }

export type CheckinField = {
  id: string
  kind: 'scale' | 'number' | 'reaction_test' | 'text'
  question: string
  domain?: string | null
  metric?: string | null
  min?: number | null
  max?: number | null
  step?: number | null
  low_label?: string | null
  high_label?: string | null
}

/** Actions the playbook held for Earth review, in words: "notify flight surgeon, checklist Radiation is rising". */
export function heldActions(playbook: Playbook | null, queued: { do: string; role?: string; checklist?: string }[] = []) {
  return queued
    .map((q) =>
      q.do === 'show_checklist'
        ? `checklist "${playbook?.checklists[q.checklist ?? '']?.title ?? q.checklist}"`
        : `${q.do.replace(/_/g, ' ')} ${(q.role ?? '').replace(/_/g, ' ')}`.trim(),
    )
    .join(', ')
}

/** "heart_rate" -> "Heart rate", for anything the playbook does not name. */
export const humanize = (s: string) => {
  const words = s.replace(/_/g, ' ')
  return words.charAt(0).toUpperCase() + words.slice(1)
}

export function severityLabel(playbook: Playbook | null, id: string) {
  return playbook?.severities.find((s) => s.id === id)?.label ?? humanize(id)
}

/** Status color by rank: the highest severity gets the act color, every lower one the watch color. Always paired with a text label. */
export function severityTone(playbook: Playbook | null, id: string | undefined) {
  if (!id) return { text: '', border: 'border-signal' }
  const top = playbook?.severities.at(-1)?.id
  return id === top
    ? { text: 'text-destructive', border: 'border-destructive' }
    : { text: 'text-warn', border: 'border-warn' }
}

const dateOnly = new Intl.DateTimeFormat('en-GB', { day: 'numeric', month: 'long', timeZone: 'UTC' })

/** A forecast time, no more precise than the forecast: a date when it is days away, a clock time when it is close. */
export const forecastTime = (eta: number, from: number) =>
  eta - from > 2 * 86_400_000 ? dateOnly.format(eta) : `${clock.format(eta)} UTC`

export const clock = new Intl.DateTimeFormat('en-GB', {
  day: 'numeric',
  month: 'short',
  hour: '2-digit',
  minute: '2-digit',
  second: '2-digit',
  timeZone: 'UTC',
})
