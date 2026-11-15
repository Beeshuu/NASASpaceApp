import { type Playbook, severityLabel } from '@/lib/playbook'

/** Status is never colour alone: a shape, a word and a colour. Ring: in range. Triangle: watch. Square: act. */
export function StatusMark({ playbook, severity, className = '' }: { playbook: Playbook | null; severity?: string; className?: string }) {
  const kind = !severity ? 'ok' : severity === playbook?.severities.at(-1)?.id ? 'act' : 'watch'
  const color = kind === 'act' ? 'text-destructive' : kind === 'watch' ? 'text-warn' : 'text-muted-foreground'
  return (
    <span className={`inline-flex items-center gap-2 text-sm font-bold tracking-widest whitespace-nowrap uppercase ${color} ${className}`}>
      <svg aria-hidden viewBox="0 0 12 12" className="size-3 shrink-0">
        {kind === 'act' ? (
          <rect width="12" height="12" fill="currentColor" />
        ) : kind === 'watch' ? (
          <path d="M6 0.5 12 11.5H0Z" fill="currentColor" />
        ) : (
          <circle cx="6" cy="6" r="4.5" fill="none" stroke="currentColor" strokeWidth="2" />
        )}
      </svg>
      {severity ? severityLabel(playbook, severity) : 'In range'}
    </span>
  )
}
