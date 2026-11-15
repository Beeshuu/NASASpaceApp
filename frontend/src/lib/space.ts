import { Body, Ecliptic, HelioVector } from 'astronomy-engine'

export const AU_KM = 149_597_870.7
const LIGHT_S_PER_AU = 499.004784

export type Kind = 'FLR' | 'CME' | 'SEP' | 'GST'

/** One NASA DONKI event, as /api/space-weather returns it. */
export type SwEvent = {
  id: string
  type: Kind
  time: number
  linked: string[]
  link?: string | null
  class?: string | null // FLR
  speed?: number // CME, km/s, from the most accurate CMEAnalysis
  lon?: number // CME, degrees from the Sun-Earth line
  half_angle?: number // CME
  t21_5?: number // CME, when the front was at 21.5 solar radii
  mars_arrival?: number | null // CME, when the front reaches Mars, if its cone covers Mars
  kp_max?: number | null // GST
}

export const KINDS: { kind: Kind; label: string; short: string }[] = [
  { kind: 'FLR', label: 'Solar flares', short: 'Flares' },
  { kind: 'CME', label: 'Coronal mass ejections', short: 'CMEs' },
  { kind: 'SEP', label: 'Particle events', short: 'Particles' },
  { kind: 'GST', label: 'Geomagnetic storms', short: 'Storms' },
]

export function describe(e: SwEvent) {
  if (e.type === 'FLR') return e.class ? `${e.class} flare` : 'Solar flare'
  if (e.type === 'CME') return e.speed ? `CME at ${Math.round(e.speed)} km/s` : 'CME'
  if (e.type === 'SEP') return 'Particle event'
  return e.kp_max ? `Geomagnetic storm, Kp ${e.kp_max}` : 'Geomagnetic storm'
}

/** Heliocentric ecliptic positions in AU (x toward the March equinox, y 90 degrees ahead), and the light time between them. */
export function sky(ts: number) {
  const date = new Date(ts)
  const e = Ecliptic(HelioVector(Body.Earth, date)).vec
  const m = Ecliptic(HelioVector(Body.Mars, date)).vec
  const distanceAu = Math.hypot(e.x - m.x, e.y - m.y, e.z - m.z)
  return { earth: { x: e.x, y: e.y }, mars: { x: m.x, y: m.y }, distanceAu, lightS: distanceAu * LIGHT_S_PER_AU }
}

/** Groups of events DONKI links to each other, oldest event first, largest groups only where they overlap. */
export function chains(events: SwEvent[]) {
  const byId = new Map(events.map((e) => [e.id, e]))
  const group = new Map<string, string>() // event id -> group root id
  const find = (id: string): string => (group.get(id) === id ? id : find(group.get(id)!))
  for (const e of events) group.set(e.id, e.id)
  for (const e of events) for (const other of e.linked) if (byId.has(other)) group.set(find(e.id), find(other))
  const out = Map.groupBy(events, (e) => find(e.id))
  return [...out.values()].filter((c) => c.length > 1).map((c) => c.toSorted((a, b) => a.time - b.time))
}

export const mmss = (s: number) => `${Math.floor(s / 60)}:${String(Math.round(s) % 60).padStart(2, '0')}`
