import { useEffect, useState } from 'react'
import { createSession, listSessions, type Session } from '../sessionApi'

export function SessionList(props: {
  activeSessionId?: string
  onSelect: (sessionId: string) => void
}) {
  const [sessions, setSessions] = useState<Session[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function refresh() {
    setLoading(true)
    setError(null)
    try {
      const res = await listSessions()
      setSessions(res.sessions)
    } catch (e: any) {
      setError(e?.message ?? String(e))
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    void refresh()
  }, [])

  async function onNew() {
    try {
      const res = await createSession({ title: null })
      await refresh()
      props.onSelect(res.session.id)
    } catch (e: any) {
      setError(e?.message ?? String(e))
    }
  }

  return (
    <div className="panel">
      <div className="panelHeader">
        <div className="panelTitle">Sessions</div>
        <div className="row">
          <button className="button secondary" onClick={() => void refresh()} disabled={loading}>
            Refresh
          </button>
          <button className="button" onClick={() => void onNew()}>
            New
          </button>
        </div>
      </div>
      {error ? <div className="error">{error}</div> : null}
      <div className="tree">
        {sessions.map((s) => {
          const selected = s.id === props.activeSessionId
          return (
            <div
              key={s.id}
              className={selected ? 'treeRow selected' : 'treeRow'}
              onClick={() => props.onSelect(s.id)}
              title={s.id}
            >
              <span className="treeIcon">•</span>
              <span className="treeName">{s.title ?? 'Untitled'}</span>
              <span className="muted" style={{ marginLeft: 'auto' }}>
                {s.last_active_at}
              </span>
            </div>
          )
        })}
        {sessions.length === 0 && !loading ? <div className="muted">No sessions yet</div> : null}
      </div>
    </div>
  )
}


