import { useEffect, useState } from 'react'
import type { EarthLinkState } from '@/hooks/use-live-readings'
import { clock } from '@/lib/playbook'
import { mmss, sky } from '@/lib/space'

/** Mars mode, the crew side of the dual timeline: how far behind Earth is, and what it has received by now. */
type Props = {
  delayS: number | null // a fixed delay set for a demo, or null for the real light delay
  missionNow: number
  link: EarthLinkState | null // from the Durable Object alarm that delivers to Earth
}

export function EarthLink({ delayS: fixed, missionNow, link }: Props) {
  // Label only. Delivery itself is the Durable Object alarm; this page never decides what Earth has.
  const delayS = fixed ?? Math.round(sky(missionNow).lightS)
  const [, tick] = useState(0)
  useEffect(() => {
    const timer = window.setInterval(() => tick((n) => n + 1), 1000)
    return () => window.clearInterval(timer)
  }, [])

  if (delayS === 0) return <p className="mt-1 text-muted-foreground">Earth link is live. Earth sees what you see.</p>

  const next = link?.next_alarm ? Math.max(0, (link.next_alarm - Date.now()) / 1000) : null
  return (
    <p className="mt-1 text-muted-foreground">
      Earth is {mmss(delayS)} behind you{fixed === null ? ', the light time from Mars today' : ''}.{' '}
      {link?.received_upto ? `It has your readings up to ${clock.format(link.received_upto)} UTC. ` : ''}
      {next !== null ? `Next delivery in ${mmss(next)}. ` : ''}
      Guidance here does not wait for Earth.
    </p>
  )
}
