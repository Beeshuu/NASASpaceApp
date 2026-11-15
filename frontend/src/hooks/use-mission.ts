import { useCallback, useEffect, useState } from 'react'
import type { Playbook } from '@/lib/playbook'

export type CrewMember = { entity_id: string; module?: string | null }

export type Role = 'crew' | 'flight_surgeon' | 'commander'

/** The signed-in user, from /api/me. `role` is null for an Auth0 account with no Vital Orbit role. */
export type Me = { email: string | null; role: Role | null; crew_id: string | null; demo: boolean; logout_url: string | null; guest: boolean }

export const isMission = (me: Me | null) => me?.role === 'flight_surgeon' || me?.role === 'commander'

/** The signed-in user, crew list and active playbook, refreshed every 10 s so new crew and new playbook versions appear without a reload. */
export function useMission() {
  const [me, setMe] = useState<Me | null>(null)
  const [crew, setCrew] = useState<CrewMember[] | null>(null)
  const [playbook, setPlaybook] = useState<Playbook | null>(null)
  const [delayS, setDelayS] = useState<number | null>(null) // a fixed demo delay, or null for the real light delay
  const [failed, setFailed] = useState(false)
  const load = useCallback(async () => {
    try {
      const [meRes, crewRes, playbookRes, missionRes] = await Promise.all([
        fetch('/api/me'),
        fetch('/api/crew'),
        fetch('/api/playbook'),
        fetch('/api/mission'),
      ])
      if (!meRes.ok) throw new Error(`me: ${meRes.status}`)
      setMe(await meRes.json())
      if (!crewRes.ok) throw new Error(`crew: ${crewRes.status}`)
      setCrew(await crewRes.json())
      setPlaybook(playbookRes.ok ? await playbookRes.json() : null) // 404 means no playbook is active
      if (missionRes.ok) setDelayS((await missionRes.json()).comm_delay_s)
      setFailed(false)
    } catch {
      setFailed(true)
    }
  }, [])
  useEffect(() => {
    load()
    const timer = window.setInterval(load, 10_000)
    return () => window.clearInterval(timer)
  }, [load])
  return { me, crew, playbook, delayS, failed, reload: load }
}
