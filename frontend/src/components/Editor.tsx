import { useEffect, useMemo, useState } from 'react'
import { fsRead, fsWrite } from '../api'

export function Editor(props: { path?: string; onSaved?: (path: string) => void }) {
  const [content, setContent] = useState('')
  const [loading, setLoading] = useState(false)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const title = useMemo(() => props.path ?? 'No file selected', [props.path])

  useEffect(() => {
    const path = props.path
    if (!path) return
    setLoading(true)
    setError(null)
    ;(async () => {
      try {
        const res = await fsRead(path)
        setContent(res.content)
      } catch (e: any) {
        setError(e?.message ?? String(e))
        setContent('')
      } finally {
        setLoading(false)
      }
    })()
  }, [props.path])

  async function save() {
    const path = props.path
    if (!path) return
    setSaving(true)
    setError(null)
    try {
      await fsWrite(path, content)
      props.onSaved?.(path)
    } catch (e: any) {
      setError(e?.message ?? String(e))
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="panel">
      <div className="panelHeader">
        <div className="panelTitle">Editor</div>
        <div className="muted">{title}</div>
        <div className="row">
          <button className="button" onClick={() => void save()} disabled={!props.path || saving}>
            {saving ? 'Saving…' : 'Save'}
          </button>
        </div>
      </div>

      {error ? <div className="error">{error}</div> : null}

      <div className="editor">
        {loading ? <div className="muted">Loading…</div> : null}
        <textarea
          className="textarea editorArea"
          value={content}
          onChange={(e) => setContent(e.target.value)}
          spellCheck={false}
          disabled={!props.path}
        />
      </div>
    </div>
  )
}



