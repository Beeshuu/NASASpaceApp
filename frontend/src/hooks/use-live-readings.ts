import { useEffect, useState } from 'react'

export type Reading = {
  domain: string
  metric: string
  value: number
  unit?: string | null
  ts: number
}

export type Alert = {
  paged?: string[] // roles the edge paged
  notified?: string[] // roles the edge notified
  id: string
  domain: string
  metric: string
  severity: string
  message: string
  ts: number
  checklist?: string // id of the playbook checklist this alert asks for
  eta?: number // forecast alerts only: when the twin expects the threshold to be crossed
  alert_crew?: 'self' | 'group' | 'all' // who else was alerted
  queued?: QueuedAction[] // actions the playbook holds for Earth review instead of running at the edge
}

export type QueuedAction = { do: string; role?: string; checklist?: string; scope?: string }

/** Another crew member's alert that reached this one through alert_crew. */
export type CrewAlert = { key: string; from: string; scope: string; message: string; severity: string; ts: number; prewarn?: boolean }

/** The digital twin's view of one indicator: measured history, smoothed level and slope, and the expected crossing. */
export type Forecast = {
  rule: string
  domain: string
  metric: string
  op: '>=' | '<='
  threshold: number
  horizon_ms: number
  level: number
  slope: number // per millisecond
  t: number
  eta: number | null
  points: [number, number][] // [ts, value]
  chronic?: { per_day: number; days: number } | null // slope of daily averages from Tiger Data
}

/** What the playbook engine concluded for this crew member. Null when no playbook is active. */
export type Status = {
  alerts: Alert[] // worst first
  domains: Record<string, string> // domain -> worst active severity
  baselines: Record<string, number> // "domain/metric" -> personal baseline, once learned
  learning: string[] // indicators whose baseline is still being learned
  forecasts: Forecast[]
  crew_alerts?: CrewAlert[]
}

/** The astronaut Durable Object's Earth delivery alarm: when it next fires, and the newest reading Earth has. */
export type EarthLinkState = { next_alarm: number | null; received_upto: number | null }

export type Link = 'connecting' | 'live' | 'lost'

export const readingKey = (r: { domain: string; metric: string }) => `${r.domain}/${r.metric}`

/**
 * Last stored values and status over HTTP, then live updates over the astronaut's WebSocket. Reconnects with backoff.
 * `earth` reads Earth's delayed copy instead: only what the crew member shares, one comm delay late.
 */
export function useLiveReadings(entityId: string | null, earth = false) {
  const [readings, setReadings] = useState<Record<string, Reading>>({})
  const [status, setStatus] = useState<Status | null>(null)
  const [link, setLink] = useState<Link>('connecting')
  const [withheld, setWithheld] = useState<string[]>([])
  const [ledgerSeq, setLedgerSeq] = useState<number | null>(null) // Earth, demo mode: newest black-box entry received
  const [earthLink, setEarthLink] = useState<EarthLinkState | null>(null)

  useEffect(() => {
    if (!entityId) return
    setEarthLink(null)
    setReadings({})
    setStatus(null)
    setLink('connecting')

    const id = encodeURIComponent(entityId)
    let ws: WebSocket | undefined
    let timer: number | undefined
    let attempt = 0
    let stopped = false

    const merge = (rows: Reading[]) =>
      setReadings((prev) => {
        const next = { ...prev }
        for (const r of rows) {
          const k = readingKey(r)
          if (!next[k] || r.ts >= next[k].ts) next[k] = r
        }
        return next
      })

    const getJson = async (path: string) => {
      const res = await fetch(`/api/astronauts/${id}/${path}`)
      if (!res.ok) throw new Error(`${path}: ${res.status}`)
      return res.json()
    }

    const connect = () => {
      const socket = new WebSocket(
        `${location.protocol === 'https:' ? 'wss' : 'ws'}://${location.host}/ws/${id}${earth ? '?as=earth' : ''}`,
      )
      ws = socket
      socket.onopen = async () => {
        try {
          if (earth) {
            const res = await fetch(`/api/earth/astronauts/${id}`)
            if (!res.ok) throw new Error(`earth: ${res.status}`)
            const view = await res.json()
            if (stopped) return
            merge(view.readings)
            setStatus(view.status)
            setWithheld(view.withheld ?? [])
          } else {
            const [latest, current, linkNow] = await Promise.all([getJson('latest'), getJson('status'), getJson('earth-link')])
            if (stopped) return
            merge(latest)
            setStatus(current)
            setEarthLink(linkNow)
          }
          attempt = 0
          setLink('live')
        } catch {
          socket.close() // falls through to onclose, which retries
        }
      }
      socket.onmessage = (e) => {
        const msg = JSON.parse(e.data)
        if (msg.type === 'crew_alert') return setStatus(msg.status)
        if (msg.type === 'earth_link') return setEarthLink({ next_alarm: msg.next_alarm, received_upto: msg.received_upto })
        if (msg.type !== 'indicators') return
        merge(msg.readings)
        setStatus(msg.status)
        if (msg.ledger_seq != null) setLedgerSeq(msg.ledger_seq)
        if (msg.withheld) {
          // Earth only: the crew member stopped sharing these, so their last values stop showing.
          setWithheld(msg.withheld)
          setReadings((prev) => Object.fromEntries(Object.entries(prev).filter(([k]) => !msg.withheld.includes(k))))
        }
      }
      socket.onclose = () => {
        if (stopped) return
        setLink('lost')
        timer = window.setTimeout(connect, Math.min(1000 * 2 ** attempt++, 15000))
      }
    }
    connect()

    return () => {
      stopped = true
      window.clearTimeout(timer)
      ws?.close()
    }
  }, [entityId, earth])

  return { readings: Object.values(readings), status, link, earthLink, withheld, ledgerSeq }
}
