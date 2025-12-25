import { useEffect, useState } from 'react'

type Pending = {
  card_id: string
  board_id: string
  updated_at: string
}

async function jsonFetch<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(path, {
    ...init,
    headers: { 'Content-Type': 'application/json', ...(init?.headers ?? {}) },
  })
  if (!res.ok) throw new Error(await res.text())
  return (await res.json()) as T
}

export function PendingPanel(props: { sessionId?: string }) {
  const [pending, setPending] = useState<Pending[]>([])
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)

  async function refresh() {
    setLoading(true)
    setError(null)
    try {
      const res = await jsonFetch<{ pending: any[] }>('/api/kanban/pending')
      setPending(
        (res.pending ?? []).map((p) => ({
          card_id: p.card_id,
          board_id: p.board_id,
          updated_at: p.updated_at,
        })),
      )
    } catch (e: any) {
      setError(e?.message ?? String(e))
    } finally {
      setLoading(false)
    }
  }

  async function approve(cardId: string) {
    await jsonFetch(`/api/kanban/pending/${encodeURIComponent(cardId)}/approve`, {
      method: 'POST',
      body: JSON.stringify({ sessionId: props.sessionId ?? null }),
    })
    await refresh()
  }

  async function reject(cardId: string) {
    await jsonFetch(`/api/kanban/pending/${encodeURIComponent(cardId)}/reject`, {
      method: 'POST',
      body: JSON.stringify({ sessionId: props.sessionId ?? null }),
    })
    await refresh()
  }

  useEffect(() => {
    void refresh()
  }, [])

  return (
    <div className="panel">
      <div className="panelHeader">
        <div className="panelTitle">Pending</div>
        <div className="muted">Notion overlays</div>
        <div className="row">
          <button className="button secondary" onClick={() => void refresh()} disabled={loading}>
            Refresh
          </button>
        </div>
      </div>
      {error ? <div className="error">{error}</div> : null}
      <div className="todoList">
        {pending.map((p) => (
          <div key={p.card_id} className="todoItem" style={{ justifyContent: 'space-between' }}>
            <div style={{ overflow: 'hidden' }}>
              <div className="todoText">{p.card_id}</div>
              <div className="muted">
                {p.board_id} · {p.updated_at}
              </div>
            </div>
            <div className="row" style={{ marginLeft: 12 }}>
              <button className="button secondary" onClick={() => void reject(p.card_id)}>
                Reject
              </button>
              <button className="button" onClick={() => void approve(p.card_id)}>
                Approve
              </button>
            </div>
          </div>
        ))}
        {pending.length === 0 ? <div className="muted">No pending changes.</div> : null}
      </div>
    </div>
  )
}


