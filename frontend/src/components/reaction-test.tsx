import { useEffect, useRef, useState } from 'react'

const TRIES = 3

type Phase = 'idle' | 'waiting' | 'go' | 'early' | 'done'

const prompt: Record<Phase, string> = {
  idle: 'Start the test',
  waiting: 'Wait for the signal',
  go: 'Press now',
  early: 'Too early. Press to try again',
  done: 'Run the test again',
}

/** Three timed presses. Reports the average in milliseconds. Works with pointer, Enter or Space. */
export function ReactionTest({ onResult }: { onResult: (ms: number | null) => void }) {
  const [phase, setPhase] = useState<Phase>('idle')
  const [times, setTimes] = useState<number[]>([])
  const timer = useRef<number | undefined>(undefined)
  const shownAt = useRef(0)
  const lastPress = useRef(0)

  useEffect(() => () => window.clearTimeout(timer.current), [])

  const arm = () => {
    setPhase('waiting')
    // Random delay so the signal cannot be anticipated.
    timer.current = window.setTimeout(() => {
      shownAt.current = performance.now()
      setPhase('go')
    }, 1500 + Math.random() * 2500)
  }

  const press = () => {
    const now = performance.now()
    if (now - lastPress.current < 250) return // one physical press can arrive as keydown and click
    lastPress.current = now

    if (phase === 'waiting') {
      window.clearTimeout(timer.current)
      setPhase('early')
    } else if (phase === 'go') {
      const next = [...times, now - shownAt.current]
      setTimes(next)
      if (next.length < TRIES) return arm()
      setPhase('done')
      onResult(Math.round(next.reduce((a, b) => a + b, 0) / TRIES))
    } else {
      if (phase !== 'early') {
        setTimes([])
        onResult(null)
      }
      arm()
    }
  }

  const average = times.length === TRIES ? Math.round(times.reduce((a, b) => a + b, 0) / TRIES) : null

  return (
    <div>
      <p className="text-muted-foreground">
        Press the button as soon as it says “Press now”. You get {TRIES} tries.
      </p>
      <button
        type="button"
        // Timed on press, not release, so the measurement does not include how long the key is held.
        onPointerDown={press}
        onKeyDown={(e) => {
          if ((e.key === 'Enter' || e.key === ' ') && !e.repeat) {
            e.preventDefault()
            press()
          }
        }}
        onClick={(e) => e.detail === 0 && press()} // assistive technology sends a click with no pointer or key event
        className={`mt-2 min-h-24 w-full rounded-md border px-4 text-xl font-bold select-none ${
          phase === 'go' ? 'border-primary bg-primary text-primary-foreground' : 'bg-muted'
        }`}
      >
        {prompt[phase]}
      </button>
      <p role="status" className="mt-2">
        {average !== null
          ? `Average of ${TRIES} tries: ${average} ms.`
          : times.length > 0 && `Try ${times.length} of ${TRIES} recorded.`}
      </p>
    </div>
  )
}
