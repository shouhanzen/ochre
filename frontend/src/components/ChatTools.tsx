import { useState } from 'react'

export type ChatMsg = {
  id?: string
  role: 'user' | 'assistant' | 'system' | 'tool'
  content: string
  ts?: string
  kind?: 'normal' | 'pending'
  requestId?: string
  meta?: Record<string, unknown>
}

export type ToolPill = {
  name: string
  status?: 'ok' | 'error'
  durationMs?: number
  argsPreview?: string
  outputPreview?: string
  rawLines: string[]
}

function _safeJsonPreview(s: string): string | null {
  const t = s.trim()
  if (!t.startsWith('{') && !t.startsWith('[')) return null
  try {
    const obj = JSON.parse(t) as any
    if (obj && typeof obj === 'object') {
      if (typeof obj.ok === 'boolean') {
        if (obj.ok === false) {
          const err = obj.error
          if (typeof err === 'string') return err
          if (err && typeof err === 'object') {
            if (typeof err.message === 'string') return err.message
            if (typeof err.code === 'string') return err.code
          }
          return 'error'
        }
        if ('result' in obj) {
          const r = obj.result
          if (r == null) return 'ok'
          if (typeof r === 'string') return r.slice(0, 140)
          if (typeof r === 'object') {
            const keys = Object.keys(r).slice(0, 6)
            return keys.length ? `result: { ${keys.join(', ')} }` : 'result: {}'
          }
          return `result: ${String(r).slice(0, 140)}`
        }
        return 'ok'
      }
    }
    return null
  } catch {
    return null
  }
}

export function parseToolPills(toolMsgs: ChatMsg[]): ToolPill[] {
  // New format: persisted tool result messages with meta.tool_call_id + meta.ok/durationMs/argsPreview.
  const structured = toolMsgs.some((m) => !!(m.meta && (m.meta as any)['tool_call_id']))
  if (structured) {
    const pills: ToolPill[] = []
    for (const m of toolMsgs) {
      const meta: any = m.meta ?? {}
      const tcId = typeof meta.tool_call_id === 'string' ? meta.tool_call_id : null
      if (!tcId) continue
      const name = (typeof meta.name === 'string' && meta.name) || 'tool'
      const ok = typeof meta.ok === 'boolean' ? meta.ok : undefined
      const durationMs = typeof meta.durationMs === 'number' ? meta.durationMs : undefined
      const argsPreview = typeof meta.argsPreview === 'string' ? meta.argsPreview : undefined
      const outPreview = _safeJsonPreview(m.content ?? '')
      pills.push({
        name,
        status: ok == null ? undefined : ok ? 'ok' : 'error',
        durationMs,
        argsPreview,
        outputPreview: outPreview ?? undefined,
        rawLines: [m.content ?? ''],
      })
    }
    return pills
  }

  const pills: ToolPill[] = []
  const startRe = /^▶\s+(\S+)\s*(.*)$/
  const endRe = /^■\s+(\S+)\s+(ok|error)\s+\((\d+)ms\)$/

  for (let i = 0; i < toolMsgs.length; i++) {
    const m = toolMsgs[i]
    const line = m.content ?? ''
    const metaName = (m.meta?.['name'] as string | undefined) ?? ''

    const start = startRe.exec(line)
    if (start) {
      const name = start[1] || metaName || 'tool'
      const args = (start[2] ?? '').trim() || undefined
      const pill: ToolPill = { name, argsPreview: args, rawLines: [line] }

      const next = toolMsgs[i + 1]
      if (next) {
        const end = endRe.exec(next.content ?? '')
        if (end && end[1] === name) {
          pill.status = end[2] as 'ok' | 'error'
          pill.durationMs = Number(end[3])
          pill.rawLines.push(next.content ?? '')
          i++

          const maybeOut = toolMsgs[i + 1]
          if (maybeOut) {
            const outName = (maybeOut.meta?.['name'] as string | undefined) ?? ''
            const outPreview = _safeJsonPreview(maybeOut.content ?? '')
            if (outPreview && (!outName || outName === name)) {
              pill.outputPreview = outPreview
              pill.rawLines.push(maybeOut.content ?? '')
              i++
            }
          }
        }
      }

      pills.push(pill)
      continue
    }

    const end = endRe.exec(line)
    if (end) {
      pills.push({
        name: end[1] || metaName || 'tool',
        status: end[2] as 'ok' | 'error',
        durationMs: Number(end[3]),
        rawLines: [line],
      })
      continue
    }

    const outPreview = _safeJsonPreview(line)
    if (outPreview) {
      pills.push({ name: metaName || 'tool', outputPreview: outPreview, rawLines: [line] })
      continue
    }

    pills.push({ name: metaName || 'tool', rawLines: [line] })
  }

  return pills
}

export function ToolList({ pills }: { pills: ToolPill[] }) {
  return (
    <div className="toolList">
      {pills.map((p, idx) => (
        <ToolItem key={idx} pill={p} />
      ))}
    </div>
  )
}

function ToolItem({ pill }: { pill: ToolPill }) {
  const [expanded, setExpanded] = useState(false)
  const [activeTab, setActiveTab] = useState<'args' | 'output'>('output')

  const hasRaw = pill.rawLines.length > 0 && pill.rawLines.some(l => l.trim().length > 0)

  return (
    <div className={`toolItem ${expanded ? 'expanded' : ''}`}>
      <div className="toolHeader" onClick={() => setExpanded(!expanded)}>
        <span className="toolIcon">{expanded ? '▼' : '▶'}</span>
        <span className="toolName">{pill.name}</span>
        <div style={{ marginLeft: 'auto', display: 'flex', gap: '8px', alignItems: 'center' }}>
          {pill.status ? <span className={`toolStatus ${pill.status}`}>{pill.status}</span> : null}
          {typeof pill.durationMs === 'number' ? <span className="toolDuration">{pill.durationMs}ms</span> : null}
        </div>
      </div>
      
      {expanded ? (
        <div className="toolBody">
          <div className="toolTabs">
            <button 
              className={`toolTab ${activeTab === 'args' ? 'active' : ''}`}
              onClick={() => setActiveTab('args')}
            >
              Arguments
            </button>
            <button 
              className={`toolTab ${activeTab === 'output' ? 'active' : ''}`}
              onClick={() => setActiveTab('output')}
            >
              Output
            </button>
            {hasRaw ? (
              <button 
                className={`toolTab ${activeTab === 'raw' ? 'active' : ''}`}
                onClick={() => setActiveTab('raw' as any)}
              >
                Raw
              </button>
            ) : null}
          </div>
          <div className="toolContent">
             <pre>
               {activeTab === 'args' 
                 ? (pill.argsPreview || '(no arguments)')
                 : activeTab === 'output' 
                   ? (pill.outputPreview || '(no output)')
                   : pill.rawLines.join('\n')
               }
             </pre>
          </div>
        </div>
      ) : null}
    </div>
  )
}

