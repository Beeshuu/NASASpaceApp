import { clock } from '@/lib/playbook'

/** One row of the black-box index, as /api/ledger and /api/ledger/queue return it. */
export type LedgerEntry = {
  seq: number
  hash: string
  prev_hash: string
  type: string
  entity_id: string | null
  timestamp: string
  summary: string
  reviewed_seq: number | null
}

export const TYPE_LABELS: Record<string, string> = {
  genesis: 'Log started',
  alert: 'Alert',
  recommendation: 'Assistant answer',
  checklist_step: 'Checklist step',
  autonomous_action: 'Edge action',
  earth_review: 'Waiting for Earth review',
  data_share: 'Data shared',
  review_approve: 'Approved by mission control',
  review_override: 'Overridden by mission control',
  playbook_switch: 'Playbook changed',
  checkpoint: 'Scheduled check',
  pre_warn: 'Module pre-warned',
  workflow_step: 'Incident response',
}

export const short = (hash: string) => hash.slice(0, 8)
export const when = (iso: string) => `${clock.format(new Date(iso))} UTC`
