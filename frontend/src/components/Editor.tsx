import { useEffect, useMemo, useState } from 'react'
import { fsList, fsMove, fsRead, fsWrite } from '../api'
import { TodoFileView } from './TodoFileView'

type TaskDoc = {
  pageId: string
  boardId: string
  title: string
  status: string
  tags: string[]
  body: string
}

function parseTaskDoc(md: string): TaskDoc {
  const lines = md.split(/\r?\n/)
  if (!lines.length || lines[0].trim() !== '---') throw new Error('Missing frontmatter start (---)')
  let end = -1
  for (let i = 1; i < lines.length; i++) {
    if (lines[i].trim() === '---') {
      end = i
      break
    }
  }
  if (end === -1) throw new Error('Missing frontmatter end (---)')

  const fm = lines.slice(1, end)
  const body = lines.slice(end + 1).join('\n').replace(/^\n+/, '')
  const kv: Record<string, string> = {}
  for (const l of fm) {
    const m = /^\s*([A-Za-z0-9_]+)\s*:\s*(.*)\s*$/.exec(l)
    if (!m) continue
    kv[m[1]] = m[2] ?? ''
  }
  const unquote = (s: string) => {
    const t = s.trim()
    if ((t.startsWith('"') && t.endsWith('"')) || (t.startsWith("'") && t.endsWith("'"))) return t.slice(1, -1)
    return t
  }
  const pageId = unquote(kv.pageId ?? kv.page_id ?? '')
  const boardId = unquote(kv.boardId ?? kv.board_id ?? 'default') || 'default'
  const title = unquote(kv.title ?? '')
  const status = unquote(kv.status ?? '')

  const tagsRaw = (kv.tags ?? '').trim()
  const tags: string[] = []
  if (tagsRaw.startsWith('[') && tagsRaw.endsWith(']')) {
    const inner = tagsRaw.slice(1, -1).trim()
    if (inner) {
      for (const part of inner.split(',')) {
        const t = unquote(part.trim())
        if (t) tags.push(t)
      }
    }
  } else if (tagsRaw) {
    const t = unquote(tagsRaw)
    if (t) tags.push(t)
  }

  if (!pageId) throw new Error('Missing pageId in frontmatter')
  if (!title) throw new Error('Missing title in frontmatter')
  return { pageId, boardId, title, status, tags, body }
}

function renderTaskDoc(d: TaskDoc): string {
  const tagsPart = `[${d.tags.map((t) => `"${t.replaceAll('"', '\\"')}"`).join(', ')}]`
  const out: string[] = [
    '---',
    `pageId: "${d.pageId.replaceAll('"', '\\"')}"`,
    `boardId: "${d.boardId.replaceAll('"', '\\"')}"`,
    `title: "${d.title.replaceAll('"', '\\"')}"`,
  ]
  if (d.status.trim()) out.push(`status: "${d.status.replaceAll('"', '\\"')}"`)
  out.push(`tags: ${tagsPart}`)
  out.push('---', '')
  if (d.body.trim()) out.push(d.body.replace(/\s+$/, '') + '\n')
  return out.join('\n')
}

type StatusOpt = { name: string; path: string }

export function Editor(props: { path?: string; onSaved?: (path: string) => void; onNavigate?: (path: string) => void }) {
  const [content, setContent] = useState('')
  const [loading, setLoading] = useState(false)
  const [saving, setSaving] = useState(false)
  const [moving, setMoving] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [task, setTask] = useState<TaskDoc | null>(null)
  const [taskError, setTaskError] = useState<string | null>(null)
  const [statusOpts, setStatusOpts] = useState<StatusOpt[]>([])
  const [todoView, setTodoView] = useState<'clicky' | 'text'>('clicky')

  const title = useMemo(() => props.path ?? 'No file selected', [props.path])
  const isTodo = !!props.path && props.path.endsWith('.todo.md')
  const isTask = !!props.path && props.path.endsWith('.task.md')

  useEffect(() => {
    const path = props.path
    if (!path || !path.endsWith('.todo.md')) return
    const k = `ochre.todoView.${path}`
    try {
      const v = localStorage.getItem(k)
      if (v === 'text' || v === 'clicky') setTodoView(v)
      else setTodoView('clicky')
    } catch {
      setTodoView('clicky')
    }
  }, [props.path])

  useEffect(() => {
    const path = props.path
    if (!path) return
    setLoading(true)
    setError(null)
    setTask(null)
    setTaskError(null)
    ;(async () => {
      try {
        const res = await fsRead(path)
        setContent(res.content)
        if (path.endsWith('.task.md')) {
          try {
            setTask(parseTaskDoc(res.content))
          } catch (e: any) {
            setTaskError(e?.message ?? String(e))
            setTask(null)
          }
        }
      } catch (e: any) {
        setError(e?.message ?? String(e))
        setContent('')
      } finally {
        setLoading(false)
      }
    })()
  }, [props.path])

  useEffect(() => {
    const path = props.path
    if (!path?.endsWith('.task.md') || !task) {
      setStatusOpts([])
      return
    }
    ;(async () => {
      try {
        const base = `/fs/kanban/notion/boards/${encodeURIComponent(task.boardId)}/status`
        const res = await fsList(base)
        const opts = (res.entries ?? [])
          .filter((e) => e.kind === 'dir')
          .map((e) => ({ name: e.name, path: e.path }))
        setStatusOpts(opts)
      } catch {
        // best-effort; no status opts
        setStatusOpts([])
      }
    })()
  }, [props.path, task?.boardId])

  async function save() {
    const path = props.path
    if (!path) return
    if (path.endsWith('.todo.md') && todoView === 'clicky') return
    setSaving(true)
    setError(null)
    try {
      if (path.endsWith('.task.md') && task) {
        const md = renderTaskDoc(task)
        await fsWrite(path, md)
        setContent(md)
      } else {
        await fsWrite(path, content)
      }
      props.onSaved?.(path)
    } catch (e: any) {
      setError(e?.message ?? String(e))
    } finally {
      setSaving(false)
    }
  }

  async function saveTodo(next: string) {
    const path = props.path
    if (!path) return
    setSaving(true)
    setError(null)
    try {
      await fsWrite(path, next)
      setContent(next)
      props.onSaved?.(path)
    } catch (e: any) {
      setError(e?.message ?? String(e))
      throw e
    } finally {
      setSaving(false)
    }
  }

  async function initTodoEmpty() {
    const path = props.path
    if (!path) return
    const template = `# Todos\n\n- [ ] Example task\n`
    await saveTodo(template)
  }

  async function moveToStatus(nextStatus: string) {
    const fromPath = props.path
    if (!fromPath || !fromPath.endsWith('.task.md') || !task) return
    const dst = statusOpts.find((s) => s.name === nextStatus)
    if (!dst) {
      // fallback: only update status field locally (does not move)
      setTask((p) => (p ? { ...p, status: nextStatus } : p))
      return
    }
    const file = fromPath.split('/').pop() ?? ''
    const toPath = `${dst.path}/${file}`
    if (toPath === fromPath) return
    setMoving(true)
    setError(null)
    try {
      await fsMove(fromPath, toPath)
      props.onNavigate?.(toPath)
      setTask((p) => (p ? { ...p, status: nextStatus } : p))
      props.onSaved?.(toPath)
    } catch (e: any) {
      setError(e?.message ?? String(e))
    } finally {
      setMoving(false)
    }
  }

  return (
    <div className="panel">
      <div className="panelHeader">
        <div className="panelTitle">Editor</div>
        <div className="muted">{title}</div>
        <div className="row">
          {isTodo ? (
            <>
              <button
                className={todoView === 'clicky' ? 'button' : 'button secondary'}
                onClick={() => {
                  const path = props.path
                  if (!path) return
                  setTodoView('clicky')
                  try {
                    localStorage.setItem(`ochre.todoView.${path}`, 'clicky')
                  } catch {
                    // ignore
                  }
                }}
              >
                Clicky
              </button>
              <button
                className={todoView === 'text' ? 'button' : 'button secondary'}
                onClick={() => {
                  const path = props.path
                  if (!path) return
                  setTodoView('text')
                  try {
                    localStorage.setItem(`ochre.todoView.${path}`, 'text')
                  } catch {
                    // ignore
                  }
                }}
              >
                Text
              </button>
            </>
          ) : null}
          <button
            className="button"
            onClick={() => void save()}
            disabled={!props.path || saving || (isTodo && todoView === 'clicky')}
            title={isTodo && todoView === 'clicky' ? 'Clicky todo view saves automatically.' : undefined}
          >
            {saving ? 'Saving…' : 'Save'}
          </button>
        </div>
      </div>

      {error ? <div className="error">{error}</div> : null}

      <div className="editor">
        {loading ? <div className="muted">Loading…</div> : null}
        {isTodo && todoView === 'clicky' && props.path ? (
          <TodoFileView
            path={props.path}
            content={content}
            saving={saving}
            onWrite={saveTodo}
            onInitEmpty={initTodoEmpty}
          />
        ) : isTask && task ? (
          <div className="taskCard">
            {taskError ? <div className="error">{taskError}</div> : null}
            <div className="taskCardGrid">
              <label className="label">
                <span>Title</span>
                <input
                  className="input"
                  value={task.title}
                  onChange={(e) => setTask((p) => (p ? { ...p, title: e.target.value } : p))}
                />
              </label>
              <label className="label">
                <span>Status</span>
                {statusOpts.length ? (
                  <select
                    className="input"
                    value={task.status}
                    onChange={(e) => void moveToStatus(e.target.value)}
                    disabled={moving}
                  >
                    {statusOpts.map((s) => (
                      <option key={s.path} value={s.name}>
                        {s.name}
                      </option>
                    ))}
                  </select>
                ) : (
                  <input
                    className="input"
                    value={task.status}
                    onChange={(e) => setTask((p) => (p ? { ...p, status: e.target.value } : p))}
                  />
                )}
              </label>
              <label className="label">
                <span>Tags</span>
                <input
                  className="input"
                  value={task.tags.join(', ')}
                  onChange={(e) =>
                    setTask((p) =>
                      p
                        ? {
                            ...p,
                            tags: e.target.value
                              .split(',')
                              .map((t) => t.trim())
                              .filter(Boolean),
                          }
                        : p,
                    )
                  }
                />
              </label>
            </div>
            <div className="taskBody">
              <div className="muted">Body (markdown)</div>
              <textarea
                className="textarea editorArea"
                value={task.body}
                onChange={(e) => setTask((p) => (p ? { ...p, body: e.target.value } : p))}
                spellCheck={false}
                disabled={!props.path}
              />
            </div>
          </div>
        ) : (
          <textarea
            className="textarea editorArea"
            value={content}
            onChange={(e) => setContent(e.target.value)}
            spellCheck={false}
            disabled={!props.path}
          />
        )}
      </div>
    </div>
  )
}



