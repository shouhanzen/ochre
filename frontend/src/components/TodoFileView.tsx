import { useMemo, useState } from 'react'

type TodoItem = {
  lineIdx: number
  checked: boolean
  text: string
}

function parseTodoItems(md: string): { lines: string[]; items: TodoItem[] } {
  const lines = md.split(/\r?\n/)
  const items: TodoItem[] = []
  const re = /^(\s*[-*]\s+\[)([ xX])(\]\s*)(.*)$/
  for (let i = 0; i < lines.length; i++) {
    const m = re.exec(lines[i] ?? '')
    if (!m) continue
    const checked = String(m[2] ?? '').toLowerCase() === 'x'
    const text = String(m[4] ?? '')
    items.push({ lineIdx: i, checked, text })
  }
  return { lines, items }
}

function setTodoLineChecked(line: string, checked: boolean): string {
  const re = /^(\s*[-*]\s+\[)([ xX])(\]\s*)(.*)$/
  const m = re.exec(line)
  if (!m) return line
  return `${m[1]}${checked ? 'x' : ' '}${m[3]}${m[4]}`
}

export function TodoFileView(props: {
  path: string
  content: string
  saving: boolean
  onWrite: (nextContent: string) => Promise<void>
  onInitEmpty: () => Promise<void>
}) {
  const { items } = useMemo(() => parseTodoItems(props.content), [props.content])
  const [draft, setDraft] = useState('')
  const [localError, setLocalError] = useState<string | null>(null)

  async function toggle(item: TodoItem) {
    setLocalError(null)
    try {
      const lines = props.content.split(/\r?\n/)
      const idx = item.lineIdx
      if (idx < 0 || idx >= lines.length) return
      lines[idx] = setTodoLineChecked(lines[idx] ?? '', !item.checked)
      await props.onWrite(lines.join('\n'))
    } catch (e: any) {
      setLocalError(e?.message ?? String(e))
    }
  }

  async function add() {
    const text = draft.trim()
    if (!text) return
    setDraft('')
    setLocalError(null)
    try {
      const base = props.content.replace(/\s+$/, '')
      const prefix = base ? base + '\n' : ''
      const next = `${prefix}- [ ] ${text}\n`
      await props.onWrite(next)
    } catch (e: any) {
      setLocalError(e?.message ?? String(e))
    }
  }

  const empty = !props.content.trim()

  return (
    <div className="todoFileView">
      <div className="muted" style={{ marginBottom: 8 }}>
        {items.length} items {props.saving ? '· saving…' : null}
      </div>

      {localError ? <div className="error">{localError}</div> : null}

      {empty ? (
        <div className="row" style={{ marginBottom: 12 }}>
          <div className="muted">This todo file is empty.</div>
          <button className="button secondary" onClick={() => void props.onInitEmpty()}>
            Initialize
          </button>
        </div>
      ) : null}

      <div className="todoList">
        {items.map((t) => (
          <label key={`${t.lineIdx}-${t.text}`} className="todoItem">
            <input type="checkbox" checked={t.checked} onChange={() => void toggle(t)} />
            <span className={t.checked ? 'todoText done' : 'todoText'}>{t.text || '(empty)'}</span>
          </label>
        ))}
        {items.length === 0 ? <div className="muted">No checkbox items found. Add one below.</div> : null}
      </div>

      <div className="row">
        <input
          className="input"
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          placeholder="Add a task…"
          onKeyDown={(e) => {
            if (e.key === 'Enter') void add()
          }}
        />
        <button className="button" onClick={() => void add()}>
          Add
        </button>
      </div>
    </div>
  )
}


