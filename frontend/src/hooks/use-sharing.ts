import { useCallback, useEffect, useState } from 'react'
import type { Privacy } from '@/lib/playbook'

export type ShareRow = { domain: string; metric: string; privacy: Privacy; shared: boolean }

/** What this crew member sends to Earth, per indicator. Each change is logged in the black box by the Worker. */
export function useSharing(entityId: string) {
  const [rows, setRows] = useState<ShareRow[] | null>(null)
  const [busy, setBusy] = useState<string | null>(null) // "domain/metric" being saved
  const [problem, setProblem] = useState<string | null>(null)
  const url = `/api/astronauts/${encodeURIComponent(entityId)}/sharing`

  const load = useCallback(async () => {
    try {
      const res = await fetch(url)
      if (!res.ok) throw new Error(String(res.status))
      setRows(await res.json())
    } catch {
      setProblem('Your sharing choices did not load. Reload the page to try again.')
    }
  }, [url])

  useEffect(() => {
    load()
  }, [load])

  const save = async (path: string, key: string, body: object) => {
    setBusy(key)
    try {
      const res = await fetch(path, {
        method: 'PUT',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify(body),
      })
      if (!res.ok) throw new Error((await res.json()).detail ?? String(res.status))
      setProblem(null)
      await load()
    } catch {
      setProblem('That change was not saved. Earth gets the same data as before. Try again.')
    } finally {
      setBusy(null)
    }
  }

  const setShared = (domain: string, metric: string, shared: boolean) => save(url, `${domain}/${metric}`, { domain, metric, shared })
  /** One logged choice for every indicator the daily check-in feeds. */
  const setCheckinShared = (shared: boolean) => save(url.replace('/sharing', '/checkin/sharing'), 'checkin', { shared })

  const isShared = (domain: string, metric: string) =>
    rows?.find((r) => r.domain === domain && r.metric === metric)?.shared ?? true

  return { rows, busy, problem, setShared, setCheckinShared, isShared }
}
