import { useCallback, useEffect, useState } from 'react'

type Row = { alert_id: string; step: number }

/** Which checklist steps this crew member has marked done, per alert. A done step is logged and stays done. */
export function useChecklists(entityId: string) {
  const [done, setDone] = useState<Record<string, number[]>>({})
  const [failed, setFailed] = useState<string | null>(null) // alert id whose last save failed
  const url = `/api/astronauts/${encodeURIComponent(entityId)}/checklists`

  const add = (rows: Row[]) =>
    setDone((prev) => {
      const next = { ...prev }
      for (const r of rows) if (!next[r.alert_id]?.includes(r.step)) next[r.alert_id] = [...(next[r.alert_id] ?? []), r.step]
      return next
    })

  useEffect(() => {
    fetch(url)
      .then((r) => (r.ok ? r.json() : []))
      .then(add)
      .catch(() => {}) // progress simply shows as not done; marking a step reports its own failure
  }, [url])

  const markDone = useCallback(
    async (alertId: string, step: number) => {
      try {
        const res = await fetch(url, {
          method: 'POST',
          headers: { 'content-type': 'application/json' },
          body: JSON.stringify({ alert_id: alertId, step }),
        })
        if (!res.ok) throw new Error(String(res.status))
        add([{ alert_id: alertId, step }])
        setFailed(null)
      } catch {
        setFailed(alertId)
      }
    },
    [url],
  )

  return { done, failed, markDone }
}
