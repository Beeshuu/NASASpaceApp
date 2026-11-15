// Magic UI "Animated Beam" (magicui.design), trimmed. With prefers-reduced-motion the beam is a still line.
import { motion, useReducedMotion } from 'motion/react'
import { type RefObject, useEffect, useId, useState } from 'react'

type Props = {
  containerRef: RefObject<HTMLElement | null>
  fromRef: RefObject<HTMLElement | null>
  toRef: RefObject<HTMLElement | null>
  curvature?: number
  duration?: number
  delay?: number
  className?: string
}

export function AnimatedBeam({ containerRef, fromRef, toRef, curvature = 0, duration = 2.5, delay = 0, className }: Props) {
  const id = useId()
  const still = useReducedMotion()
  const [path, setPath] = useState('')
  const [box, setBox] = useState({ w: 0, h: 0 })

  useEffect(() => {
    const update = () => {
      const c = containerRef.current?.getBoundingClientRect()
      const a = fromRef.current?.getBoundingClientRect()
      const b = toRef.current?.getBoundingClientRect()
      if (!c || !a || !b) return
      const sx = a.left - c.left + a.width / 2
      const sy = a.top - c.top + a.height / 2
      const ex = b.left - c.left + b.width / 2
      const ey = b.top - c.top + b.height / 2
      setBox({ w: c.width, h: c.height })
      setPath(`M ${sx},${sy} Q ${(sx + ex) / 2},${sy - curvature} ${ex},${ey}`)
    }
    update()
    const ro = new ResizeObserver(update)
    if (containerRef.current) ro.observe(containerRef.current)
    return () => ro.disconnect()
  }, [containerRef, fromRef, toRef, curvature])

  return (
    <svg
      aria-hidden="true"
      width={box.w}
      height={box.h}
      viewBox={`0 0 ${box.w} ${box.h}`}
      className={`pointer-events-none absolute left-0 top-0 ${className ?? ''}`}
    >
      <path d={path} className="stroke-warn" strokeWidth={2} strokeOpacity={still ? 0.7 : 0.2} fill="none" strokeLinecap="round" />
      {!still && (
        <>
          <path d={path} stroke={`url(#${id})`} strokeWidth={2} strokeLinecap="round" fill="none" />
          <defs>
            <motion.linearGradient
              id={id}
              gradientUnits="userSpaceOnUse"
              initial={{ x1: '0%', x2: '0%', y1: '0%', y2: '0%' }}
              animate={{ x1: ['0%', '100%'], x2: ['10%', '110%'], y1: ['0%', '0%'], y2: ['0%', '0%'] }}
              transition={{ duration, delay, ease: [0.16, 1, 0.3, 1], repeat: Infinity, repeatDelay: 0.5 }}
            >
              <stop stopColor="var(--warn)" stopOpacity="0" />
              <stop stopColor="var(--warn)" />
              <stop offset="100%" stopColor="var(--warn)" stopOpacity="0" />
            </motion.linearGradient>
          </defs>
        </>
      )}
    </svg>
  )
}
