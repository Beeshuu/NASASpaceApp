import { useEffect, useState } from 'react'

const reduced = () => window.matchMedia('(prefers-reduced-motion: reduce)').matches

/** A live number. It counts up once when it first appears; after that a change is marked for a moment. */
export function Ticker({ value, format }: { value: number; format: (n: number) => string }) {
  const [settled, setSettled] = useState(reduced)
  const [shown, setShown] = useState(0)
  const [first] = useState(value)

  useEffect(() => {
    if (settled) return
    let frame = 0
    const t0 = performance.now()
    const tick = (now: number) => {
      const p = Math.min(1, (now - t0) / 600)
      setShown(value * (1 - (1 - p) ** 4))
      if (p < 1) frame = requestAnimationFrame(tick)
      else setSettled(true)
    }
    frame = requestAnimationFrame(tick)
    return () => cancelAnimationFrame(frame)
  }, [value, settled])

  // keyed by value so the highlight replays on every change
  return settled ? (
    <span key={value} className={value === first ? undefined : 'value-changed rounded-sm'}>
      {format(value)}
    </span>
  ) : (
    <span>{format(shown)}</span>
  )
}
