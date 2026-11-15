import { useCallback, useEffect, useState } from 'react'
import { Button } from '@/components/ui/button'

type Version = { name: string; version: number; active: number }

/** Live switch between stored playbook versions. Deprecated versions are not offered. Each switch is logged in the black box. */
type Props = {
  onSwitched: () => void
  /** Offer only these playbook names. */
  only?: string[]
}

export function PlaybookSwitcher({ onSwitched, only }: Props) {
  const [versions, setVersions] = useState<Version[] | null>(null)
  const [busy, setBusy] = useState(false)
  const [problem, setProblem] = useState<string | null>(null)
  // A switch changes the rules for the whole crew, so picking and activating are two steps.
  const [pick, setPick] = useState<string | null>(null)

  const load = useCallback(async () => {
    try {
      const res = await fetch('/api/playbooks')
      if (res.ok) setVersions((await res.json()).filter((v: Version) => !only || only.includes(v.name)))
    } catch {
      // keep the last list; the next poll tries again
    }
  }, [])

  useEffect(() => {
    load()
    const timer = window.setInterval(load, 10_000)
    return () => window.clearInterval(timer)
  }, [load])

  const change = async (value: string) => {
    const [name, version] = value.split('@')
    setBusy(true)
    try {
      const res = await fetch('/api/playbook/activate', {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify({ name, version: Number(version) }),
      })
      if (!res.ok) {
        setProblem((await res.json()).detail ?? 'The playbook did not change.')
      } else {
        setProblem(null)
        setPick(null)
        await load()
        onSwitched()
      }
    } catch {
      setProblem('The playbook did not change. Check the connection.')
    } finally {
      setBusy(false)
    }
  }

  if (!versions?.length) return null
  const active = versions.find((v) => v.active)
  const names = [...new Set(versions.map((v) => v.name))]
  const current = active ? `${active.name}@${active.version}` : ''
  return (
    <div className="flex flex-wrap items-center gap-2">
      <label htmlFor="playbook" className="label">
        Playbook
      </label>
      <select
        id="playbook"
        value={pick ?? current}
        disabled={busy}
        onChange={(e) => setPick(e.target.value === current ? null : e.target.value)}
        className="field"
      >
        {!active && <option value="">None active</option>}
        {names.map((name) => (
          <optgroup key={name} label={name}>
            {versions
              .filter((v) => v.name === name)
              .map((v) => (
                <option key={v.version} value={`${v.name}@${v.version}`}>
                  {v.name} v{v.version}
                </option>
              ))}
          </optgroup>
        ))}
      </select>
      {pick && (
        <Button disabled={busy} onClick={() => change(pick)}>
          {busy ? 'Activating' : 'Activate'}
        </Button>
      )}
      {problem && (
        <span role="alert" className="text-sm text-warn">
          {problem}
        </span>
      )}
    </div>
  )
}
