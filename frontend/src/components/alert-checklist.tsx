import { Button } from '@/components/ui/button'
import type { Checklist } from '@/lib/playbook'

type Props = {
  checklist: Checklist
  done: number[]
  failed: boolean
  open: boolean
  onDone: (step: number) => void
}

/** The steps the playbook prescribes for one alert. The crew member marks each step done, and each mark is logged. */
export function AlertChecklist({ checklist, done, failed, open, onDone }: Props) {
  const total = checklist.steps.length
  const next = checklist.steps.findIndex((_, i) => !done.includes(i))
  return (
    <details open={open} className="mt-4 border-t">
      <summary className="flex min-h-11 items-center justify-between gap-3 font-bold">
        <span>
          {checklist.title} <span className="font-normal text-muted-foreground">{done.length} of {total} done</span>
        </span>
        <span className="chevron" />
      </summary>
      <ol>
        {checklist.steps.map((text, i) => (
          <li key={i} className="flex items-center justify-between gap-4 border-t py-2">
            <span className="flex gap-3">
              <span className="text-muted-foreground">{String(i + 1).padStart(2, '0')}</span>
              <span className={done.includes(i) ? 'text-muted-foreground' : ''}>{text}</span>
            </span>
            {done.includes(i) ? (
              <span className="label px-4">Done</span>
            ) : (
              // Only the next step is filled, so there is one obvious thing to press.
              <Button variant={i === next ? 'default' : 'outline'} aria-label={`Mark step ${i + 1} done: ${checklist.title}`} onClick={() => onDone(i)}>
                Mark done
              </Button>
            )}
          </li>
        ))}
      </ol>
      <p role="status" className="mt-2">
        {failed
          ? <span className="text-warn">That step was not saved. Check the connection and mark it again.</span>
          : done.length === total && 'All steps are done and logged.'}
      </p>
    </details>
  )
}
