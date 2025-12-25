import { useEffect, useMemo, useState } from 'react'
import { addTodayTodo, getTodayTodos, setTodayTodoDone, type Task } from '../api'

export function TodoPanel(props: { refreshKey?: number }) {
  const [day, setDay] = useState<string>('')
  const [tasks, setTasks] = useState<Task[]>([])
  const [draft, setDraft] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const remaining = useMemo(() => tasks.filter((t) => !t.done).length, [tasks])

  async function refresh() {
    setLoading(true)
    setError(null)
    try {
      const res = await getTodayTodos()
      setDay(res.day)
      setTasks(res.tasks)
    } catch (e: any) {
      setError(e?.message ?? String(e))
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    void refresh()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [props.refreshKey])

  async function toggle(t: Task) {
    try {
      const res = await setTodayTodoDone(t.id, !t.done)
      setTasks(res.tasks)
    } catch (e: any) {
      setError(e?.message ?? String(e))
    }
  }

  async function add() {
    const text = draft.trim()
    if (!text) return
    setDraft('')
    try {
      const res = await addTodayTodo(text)
      setTasks(res.tasks)
    } catch (e: any) {
      setError(e?.message ?? String(e))
    }
  }

  return (
    <div className="panel">
      <div className="panelHeader">
        <div className="panelTitle">Today</div>
        <div className="muted">
          {day ? day : '…'} · {remaining} remaining
        </div>
        <div className="row">
          <button className="button secondary" onClick={refresh} disabled={loading}>
            Refresh
          </button>
        </div>
      </div>

      {error ? <div className="error">{error}</div> : null}

      <div className="todoList">
        {tasks.map((t) => (
          <label key={t.id} className="todoItem">
            <input type="checkbox" checked={t.done} onChange={() => void toggle(t)} />
            <span className={t.done ? 'todoText done' : 'todoText'}>{t.text}</span>
          </label>
        ))}
        {tasks.length === 0 && !loading ? <div className="muted">No tasks (edit template.md?)</div> : null}
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



