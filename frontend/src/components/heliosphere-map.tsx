import { useMemo } from 'react'
import { clock } from '@/lib/playbook'
import { AU_KM, sky, type SwEvent } from '@/lib/space'

const EXTENT = 1.9 // AU from the Sun to the edge of the map: Mars at its farthest is 1.67
const CME_START_AU = 0.1 // DONKI reports each CME at 21.5 solar radii

type Props = { t: number; events: SwEvent[]; pulses: boolean }

/** Top-down view of the inner solar system at time t: Sun, Earth and Mars at their real positions, CME fronts in transit. */
export function HeliosphereMap({ t, events, pulses }: Props) {
  const { earth, mars, distanceAu, lightS } = sky(t)

  // Each CME's direction is fixed at launch: DONKI gives its longitude from the Sun-Earth line at that time.
  const cones = useMemo(
    () =>
      events
        .filter((e) => e.type === 'CME' && e.speed && e.t21_5)
        .map((e) => {
          const at = sky(e.t21_5!).earth
          return { e, angle: Math.atan2(at.y, at.x) + (e.lon! * Math.PI) / 180, half: (e.half_angle! * Math.PI) / 180 }
        }),
    [events],
  )
  const active = cones
    .map((c) => ({ ...c, r: CME_START_AU + (c.e.speed! * (t - c.e.t21_5!)) / 1000 / AU_KM }))
    .filter((c) => t >= c.e.t21_5! && c.r <= EXTENT * 1.3)

  // SVG y grows downward, so every y is negated to keep the planets orbiting counterclockwise.
  const point = (r: number, a: number) => `${r * Math.cos(a)} ${-r * Math.sin(a)}`
  const lightMs = lightS * 1000

  return (
    <figure>
      <div className="frame">
        {/* decorative star field; the map reads without it */}
        <img src="/starfield.webp" alt="" loading="lazy" decoding="async" className="absolute inset-0 size-full object-cover opacity-70" />
      <svg
        viewBox={`${-EXTENT} ${-EXTENT} ${2 * EXTENT} ${2 * EXTENT}`}
        role="img"
        aria-label={`Top-down view of the inner solar system on ${clock.format(t)} UTC. Earth and Mars are ${distanceAu.toFixed(2)} AU apart. ${active.length} CME fronts are in transit.`}
        className="relative aspect-square w-full"
      >
        {[earth, mars].map((p, i) => (
          <circle key={i} r={Math.hypot(p.x, p.y)} fill="none" stroke="var(--input)" strokeWidth="1.5" strokeDasharray="1 7" strokeLinecap="round" vectorEffect="non-scaling-stroke" className="drift" />
        ))}

        {active.map(({ e, angle, half, r }) => {
          const hitsMars = Boolean(e.mars_arrival)
          const arc = `A ${r} ${r} 0 ${half > Math.PI / 2 ? 1 : 0} 0 ${point(r, angle + half)}`
          return (
            <g key={e.id} stroke={hitsMars ? 'var(--warn)' : 'var(--signal)'} fill={hitsMars ? 'var(--warn)' : 'var(--signal)'} strokeDasharray={hitsMars ? '8 5' : undefined}>
              <path d={`M 0 0 L ${point(r, angle - half)} ${arc} Z`} fillOpacity="0.1" stroke="none" />
              <path d={`M ${point(r, angle - half)} ${arc}`} fill="none" strokeWidth="2" vectorEffect="non-scaling-stroke" />
            </g>
          )
        })}

        <line x1={mars.x} y1={-mars.y} x2={earth.x} y2={-earth.y} stroke="var(--muted-foreground)" strokeWidth="1" strokeDasharray="4 4" vectorEffect="non-scaling-stroke" />
        {pulses &&
          [0, 1, 2].map((k) => {
            const p = (((t / lightMs) * 3 + k) % 3) / 3 // three signals in flight, each takes one light time
            return <circle key={k} cx={mars.x + p * (earth.x - mars.x)} cy={-(mars.y + p * (earth.y - mars.y))} r="0.03" fill="var(--foreground)" />
          })}

        <circle r="0.07" fill="var(--foreground)" />
        <circle cx={earth.x} cy={-earth.y} r="0.05" fill="var(--foreground)" />
        <circle cx={mars.x} cy={-mars.y} r="0.045" fill="var(--background)" stroke="var(--foreground)" strokeWidth="2" vectorEffect="non-scaling-stroke" />
        <g fontSize="0.13" fill="var(--foreground)">
          <text x="0.1" y="0.14">Sun</text>
          <text x={earth.x + 0.08} y={-earth.y + 0.04}>Earth</text>
          <text x={mars.x + 0.08} y={-mars.y + 0.04}>Mars</text>
        </g>
      </svg>
      </div>
      <figcaption className="mt-3 text-sm text-muted-foreground">
        Wedges are CME fronts. A dashed amber wedge is on course for Mars.
      </figcaption>
    </figure>
  )
}
