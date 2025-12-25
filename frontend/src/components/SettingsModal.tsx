import { useEffect, useState } from 'react'

async function jsonFetch<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(path, {
    ...init,
    headers: { 'Content-Type': 'application/json', ...(init?.headers ?? {}) },
  })
  if (!res.ok) throw new Error(await res.text())
  return (await res.json()) as T
}

export function SettingsModal(props: { open: boolean; onClose: () => void }) {
  const [defaultModel, setDefaultModel] = useState('')
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (!props.open) return
    setError(null)
    ;(async () => {
      try {
        const res = await jsonFetch<{ defaultModel: string }>('/api/settings')
        setDefaultModel(res.defaultModel)
      } catch (e: any) {
        setError(e?.message ?? String(e))
      }
    })()
  }, [props.open])

  async function save() {
    setSaving(true)
    setError(null)
    try {
      const res = await jsonFetch<{ defaultModel: string }>('/api/settings', {
        method: 'PUT',
        body: JSON.stringify({ defaultModel }),
      })
      setDefaultModel(res.defaultModel)
      props.onClose()
    } catch (e: any) {
      setError(e?.message ?? String(e))
    } finally {
      setSaving(false)
    }
  }

  if (!props.open) return null

  return (
    <div className="modalBackdrop" onMouseDown={props.onClose}>
      <div className="modal" onMouseDown={(e) => e.stopPropagation()}>
        <div className="panelHeader">
          <div className="panelTitle">Settings</div>
          <div className="row">
            <button className="button secondary" onClick={props.onClose}>
              Close
            </button>
            <button className="button" onClick={() => void save()} disabled={saving}>
              {saving ? 'Saving…' : 'Save'}
            </button>
          </div>
        </div>
        {error ? <div className="error">{error}</div> : null}
        <div style={{ padding: 12, display: 'flex', flexDirection: 'column', gap: 10 }}>
          <label className="label" style={{ justifyContent: 'space-between' }}>
            Default model
            <input className="input" value={defaultModel} onChange={(e) => setDefaultModel(e.target.value)} />
          </label>
          <div className="muted">
            This is stored in the backend and used for all sessions unless a request explicitly overrides it.
          </div>
        </div>
      </div>
    </div>
  )
}


