import { useState, useEffect } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { fsRead, fsWrite } from '../api'
import { TodoFileView } from './TodoFileView'

export interface WidgetProps {
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  config: any
  onSend: (text: string) => void
}

export function WidgetButtons({ config, onSend }: WidgetProps) {
  // Config can be string[] or { label: string, value: string }[]
  const buttons = Array.isArray(config) ? config : []
  
  return (
    <div className="widget-buttons" style={{ display: 'flex', gap: '8px', flexWrap: 'wrap', marginTop: '8px', marginBottom: '8px' }}>
      {/* eslint-disable-next-line @typescript-eslint/no-explicit-any */}
      {buttons.map((btn: any, i: number) => {
        const label = typeof btn === 'string' ? btn : btn.label
        const value = typeof btn === 'string' ? btn : (btn.value || btn.label)
        
        return (
          <button 
            key={i} 
            className="button secondary" 
            onClick={() => onSend(value)}
            style={{ fontSize: '0.9em' }}
          >
            {label}
          </button>
        )
      })}
    </div>
  )
}

export function WidgetSelect({ config, onSend }: WidgetProps) {
  // Config: { title?: string, options: string[], multiple?: boolean }
  const [selected, setSelected] = useState<Set<string>>(new Set())
  const options = Array.isArray(config.options) ? (config.options as string[]) : []
  const multiple = !!config.multiple

  const toggle = (val: string) => {
    const next = new Set(multiple ? selected : [])
    if (next.has(val)) next.delete(val)
    else next.add(val)
    setSelected(next)
  }

  const submit = () => {
    const vals = Array.from(selected)
    if (vals.length === 0) return
    onSend(vals.join(', '))
  }

  return (
    <div className="widget-select" style={{ border: '1px solid var(--border)', padding: '12px', borderRadius: '6px', margin: '8px 0' }}>
      {config.title ? <div style={{ fontWeight: 600, marginBottom: '8px' }}>{config.title as string}</div> : null}
      <div style={{ display: 'flex', flexDirection: 'column', gap: '4px' }}>
        {options.map((opt: string, i: number) => (
          <label key={i} style={{ display: 'flex', alignItems: 'center', gap: '8px', cursor: 'pointer' }}>
            <input 
              type={multiple ? 'checkbox' : 'radio'} 
              checked={selected.has(opt)}
              onChange={() => toggle(opt)}
              name={multiple ? undefined : 'widget-select-group'}
            />
            <span>{opt}</span>
          </label>
        ))}
      </div>
      <div style={{ marginTop: '12px' }}>
        <button 
          className="button primary" 
          disabled={selected.size === 0}
          onClick={submit}
        >
          Submit
        </button>
      </div>
    </div>
  )
}

// eslint-disable-next-line @typescript-eslint/no-explicit-any
export function WidgetFile({ config }: { config: any }) {
  // Config: { path: string, startLine?: number, endLine?: number }
  const [content, setContent] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [expanded, setExpanded] = useState(false)

  const path = config.path as string
  const isTodo = path.endsWith('.todo.md') || path.endsWith('.md.todo')
  const isMarkdown = path.endsWith('.md') && !isTodo
  
  // Reset state if path changes
  useEffect(() => {
    setContent(null)
    setExpanded(false)
    setError(null)
    setLoading(false)
    setSaving(false)
  }, [path])

  const toggleExpand = async () => {
    if (!expanded && content === null && !loading) {
      setLoading(true)
      try {
        const res = await fsRead(path)
        setContent(res.content || '')
      } catch (e) {
        setError(String(e))
      } finally {
        setLoading(false)
      }
    }
    setExpanded(!expanded)
  }

  const handleWrite = async (next: string) => {
    setSaving(true)
    setError(null)
    try {
      await fsWrite(path, next)
      setContent(next)
    } catch (e) {
      setError(String(e))
    } finally {
      setSaving(false)
    }
  }

  const handleInitEmpty = async () => {
    const template = `# Todos\n\n- [ ] Example task\n`
    await handleWrite(template)
  }

  return (
    <div className="widget-file" style={{ border: '1px solid var(--border)', borderRadius: '6px', margin: '8px 0', overflow: 'hidden' }}>
      <div 
        style={{ 
          padding: '8px 12px', 
          background: 'var(--bg-subtle)', 
          cursor: 'pointer',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          fontSize: '0.9em',
          userSelect: 'none'
        }}
        onClick={toggleExpand}
      >
        <span style={{ fontFamily: 'monospace' }}>📄 {path}</span>
        <span>{expanded ? '▼' : '▶'}</span>
      </div>
      
      {expanded ? (
        <div style={{ padding: '0', borderTop: '1px solid var(--border)', background: 'var(--bg)' }}>
          {loading ? (
            <div style={{ padding: '12px', color: 'var(--fg-muted)' }}>Loading...</div>
          ) : error ? (
            <div style={{ padding: '12px', color: 'var(--red)' }}>Error: {error}</div>
          ) : isTodo && content !== null ? (
            <TodoFileView
              path={path}
              content={content}
              saving={saving}
              onWrite={handleWrite}
              onInitEmpty={handleInitEmpty}
            />
          ) : isMarkdown && content !== null ? (
            <div className="editorArea" style={{ padding: '12px', overflow: 'auto', maxHeight: '300px', fontSize: '13px' }}>
              <div className="chatContent md">
                <ReactMarkdown remarkPlugins={[remarkGfm]}>{content}</ReactMarkdown>
              </div>
            </div>
          ) : (
            <pre style={{ margin: 0, padding: '12px', overflow: 'auto', maxHeight: '300px', fontSize: '12px', whiteSpace: 'pre-wrap', wordBreak: 'break-word' }}>
              <code>{content}</code>
            </pre>
          )}
        </div>
      ) : null}
    </div>
  )
}
