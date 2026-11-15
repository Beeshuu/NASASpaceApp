import { useEffect, useState } from 'react'
import type { CrewAlert } from '@/hooks/use-live-readings'

export type HabitatCrew = {
  entity_id: string
  module: string | null
  own: { rule: string; message: string; severity: string; ts: number }[] // group-wide alerts this crew member's own sensors raised
  prewarned: CrewAlert[] // warnings from a module mate, before their own readings changed
}

/** Modules, who is in them and which group-wide warning is spreading, polled every 3 s. */
export function useHabitat() {
  const [crew, setCrew] = useState<HabitatCrew[] | null>(null)
  useEffect(() => {
    let alive = true
    const load = async () => {
      try {
        const res = await fetch('/api/habitat')
        if (res.ok && alive) setCrew(await res.json())
      } catch {
        /* keep the last map */
      }
    }
    load()
    const t = window.setInterval(load, 3000)
    return () => {
      alive = false
      window.clearInterval(t)
    }
  }, [])
  return crew
}
