import { useEffect, useMemo, useRef, useState } from 'react'

import { getSession, type SessionMessage } from '../sessionApi'
import { SessionSocket, type WsFrame } from '../ws'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'

type ChatMsg = {
  role: 'user' | 'assistant' | 'system' | 'tool'
  content: string
  ts?: string
  kind?: 'normal' | 'pending'
  requestId?: string
  meta?: Record<string, unknown>
}

function toChatMsgs(msgs: SessionMessage[]): ChatMsg[] {
  return msgs
    .filter((m) => m.role === 'user' || m.role === 'assistant' || m.role === 'system' || m.role === 'tool')
    .map((m) => ({ role: m.role as any, content: m.content ?? '', ts: m.created_at, meta: m.meta ?? {} }))
}

type RenderItem =
  | { kind: 'msg'; msg: ChatMsg; key: string }
  | { kind: 'tools'; msgs: ChatMsg[]; key: string }

type ToolPill = {
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
        if (obj.ok === false) return String(obj.error ?? 'error')
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

function parseToolPills(toolMsgs: ChatMsg[]): ToolPill[] {
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

function groupRenderItems(msgs: ChatMsg[]): RenderItem[] {
  const out: RenderItem[] = []
  let i = 0
  while (i < msgs.length) {
    const m = msgs[i]
    if (m.role === 'tool') {
      const start = i
      while (i < msgs.length && msgs[i].role === 'tool') i++
      const chunk = msgs.slice(start, i)
      out.push({ kind: 'tools', msgs: chunk, key: `tools-${start}-${i}` })
      continue
    }
    out.push({ kind: 'msg', msg: m, key: `msg-${i}` })
    i++
  }
  return out
}

function Markdown({ text }: { text: string }) {
  return (
    <ReactMarkdown
      remarkPlugins={[remarkGfm]}
      components={{
        a: (props) => <a {...props} target="_blank" rel="noreferrer" />,
        pre: (props) => <pre className="mdPre" {...props} />,
        code: ({ className, ...props }) => <code className={`mdCode ${className ?? ''}`} {...props} />,
      }}
    >
      {text}
    </ReactMarkdown>
  )
}

export function ChatPanel(props: { sessionId?: string }) {
  const [messages, setMessages] = useState<ChatMsg[]>([])
  const [draft, setDraft] = useState('')
  const [streaming, setStreaming] = useState(false)
  const [pending, setPending] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [sock, setSock] = useState<SessionSocket | null>(null)

  const bottomRef = useRef<HTMLDivElement | null>(null)
  const streamingAssistantIdxRef = useRef<number | null>(null)
  const pendingIdxRef = useRef<number | null>(null)
  const activeRequestIdRef = useRef<string | null>(null)
  const pendingRequestIdRef = useRef<string | null>(null)

  const canSend = useMemo(() => draft.trim().length > 0 && !streaming, [draft, streaming])

  useEffect(() => {
    const sid = props.sessionId
    if (!sid) return
    setError(null)
    ;(async () => {
      try {
        const res = await getSession(sid)
        setMessages(toChatMsgs(res.messages))
        streamingAssistantIdxRef.current = null
        pendingIdxRef.current = null
        activeRequestIdRef.current = null
        pendingRequestIdRef.current = null
        setPending(false)
      } catch (e: any) {
        setError(e?.message ?? String(e))
      }
    })()
  }, [props.sessionId])

  useEffect(() => {
    const sid = props.sessionId
    if (!sid) return
    const s = new SessionSocket(sid, (f: WsFrame) => {
      // Only process frames for the active request (or system messages).
      if (f.type !== 'system.message') {
        if (activeRequestIdRef.current && f.requestId && f.requestId !== activeRequestIdRef.current) return
      }

      if (f.type === 'chat.delta') {
        // first token => stop showing the "Running tools…" indicator
        if (pendingRequestIdRef.current && f.requestId === pendingRequestIdRef.current) {
          pendingRequestIdRef.current = null
          setPending(false)
        }
        setMessages((prev) => {
          const copy = prev.slice()
          const rid = String(f.requestId ?? activeRequestIdRef.current ?? '')
          const text = String(f.payload?.text ?? '')

          // Simple rule: append to the most recent assistant bubble IF it is the most recent bubble for this request.
          const last = copy[copy.length - 1]
          if (last?.role === 'assistant' && last.requestId === rid) {
            copy[copy.length - 1] = { ...last, content: (last.content ?? '') + text }
            return copy
          }

          // Otherwise create a new assistant bubble segment (this enables true interleaving around tool bubbles).
          copy.push({ role: 'assistant', content: text, ts: new Date().toISOString(), kind: 'normal', requestId: rid })
          return copy
        })
        bottomRef.current?.scrollIntoView({ block: 'end' })
      } else if (f.type === 'chat.started') {
        setStreaming(true)
        pendingRequestIdRef.current = String(f.requestId ?? activeRequestIdRef.current ?? null)
        setPending(true)
      } else if (f.type === 'chat.done') {
        setStreaming(false)
        streamingAssistantIdxRef.current = null
        pendingIdxRef.current = null
        activeRequestIdRef.current = null
        pendingRequestIdRef.current = null
        setPending(false)
      } else if (f.type === 'chat.cancelled') {
        setStreaming(false)
        streamingAssistantIdxRef.current = null
        pendingIdxRef.current = null
        activeRequestIdRef.current = null
        pendingRequestIdRef.current = null
        setPending(false)
        setMessages((prev) => [...prev, { role: 'system', content: 'Generation cancelled.', ts: new Date().toISOString() }])
      } else if (f.type === 'chat.error') {
        setStreaming(false)
        streamingAssistantIdxRef.current = null
        pendingIdxRef.current = null
        activeRequestIdRef.current = null
        pendingRequestIdRef.current = null
        setPending(false)
        setError(String(f.payload?.message ?? 'Chat error'))
      } else if (f.type === 'system.message') {
        const c = String(f.payload?.content ?? '')
        if (c.trim()) setMessages((prev) => [...prev, { role: 'system', content: c, ts: new Date().toISOString() }])
      } else if (f.type === 'tool.start') {
        const tool = String(f.payload?.tool ?? 'tool')
        const args = String(f.payload?.argsPreview ?? '')
        const line = args ? `▶ ${tool} ${args}` : `▶ ${tool}`
        setMessages((prev) => [
          ...prev,
          { role: 'tool', content: line, ts: new Date().toISOString(), requestId: String(f.requestId ?? activeRequestIdRef.current ?? ''), kind: 'normal' },
        ])
        bottomRef.current?.scrollIntoView({ block: 'end' })
      } else if (f.type === 'tool.end') {
        const tool = String(f.payload?.tool ?? 'tool')
        const ok = !!f.payload?.ok
        const ms = Number(f.payload?.durationMs ?? 0)
        const line = `■ ${tool} ${ok ? 'ok' : 'error'} (${ms}ms)`
        setMessages((prev) => [
          ...prev,
          { role: 'tool', content: line, ts: new Date().toISOString(), requestId: String(f.requestId ?? activeRequestIdRef.current ?? ''), kind: 'normal' },
        ])
        bottomRef.current?.scrollIntoView({ block: 'end' })
      }
    })
    s.connect()
    setSock(s)
    return () => s.close()
  }, [props.sessionId])

  async function onSend() {
    if (!canSend) return
    if (!props.sessionId) return
    setError(null)
    const userMsg: ChatMsg = { role: 'user', content: draft.trim(), ts: new Date().toISOString() }
    setDraft('')
    const requestId = crypto.randomUUID()
    activeRequestIdRef.current = requestId
    pendingIdxRef.current = null
    streamingAssistantIdxRef.current = null
    pendingRequestIdRef.current = requestId
    setPending(false)
    setMessages((prev) => [...prev, userMsg])
    sock?.sendChat(userMsg.content, requestId)
  }

  return (
    <div className="panel">
      <div className="panelHeader">
        <div className="panelTitle">Chat</div>
        <div className="muted">Backend default model</div>
      </div>

      <div className="chatLog">
        {messages.length === 0 ? (
          <div className="muted">Ask the agent to view/edit `/fs/todos/today.md` or `/fs/mnt/workspace/...`.</div>
        ) : null}
        {groupRenderItems(messages).map((it) => {
          if (it.kind === 'msg') {
            const m = it.msg
            return (
              <div key={it.key} className={`chatLine ${m.role}`} data-kind={m.kind ?? 'normal'}>
                <div className="chatLineHeader">
                  <span className="chatRole">{m.role}</span>
                  {m.ts ? <span className="chatTs">{m.ts}</span> : null}
                </div>
                <div className="chatContent md">
                  <Markdown text={m.content} />
                </div>
              </div>
            )
          }

          const pills = parseToolPills(it.msgs)
          return (
            <details key={it.key} className="toolGroup">
              <summary className="toolGroupSummary">
                <span className="toolGroupTitle">Tools</span>
                <span className="toolGroupCount">{pills.length}</span>
              </summary>
              <div className="toolPills">
                {pills.map((p, idx) => (
                  <details key={idx} className="toolPill">
                    <summary className="toolPillSummary">
                      <span className="toolPillName">{p.name}</span>
                      {p.status ? <span className={`toolPillStatus ${p.status}`}>{p.status}</span> : null}
                      {typeof p.durationMs === 'number' ? <span className="toolPillMs">{p.durationMs}ms</span> : null}
                    </summary>
                    <div className="toolPillBody">
                      {p.argsPreview ? <div className="toolPillRow"><span className="muted">args</span><pre className="toolPillPre">{p.argsPreview}</pre></div> : null}
                      {p.outputPreview ? <div className="toolPillRow"><span className="muted">output</span><pre className="toolPillPre">{p.outputPreview}</pre></div> : null}
                      <div className="toolPillRow">
                        <span className="muted">raw</span>
                        <pre className="toolPillPre">{p.rawLines.join('\n')}</pre>
                      </div>
                    </div>
                  </details>
                ))}
              </div>
            </details>
          )
        })}
        {pending ? (
          <div className="chatLine assistant" data-kind="pending">
            <div className="chatLineHeader">
              <span className="chatRole">assistant</span>
            </div>
            <div className="chatContent">Running tools…</div>
          </div>
        ) : null}
        <div ref={bottomRef} />
      </div>

      {error ? <div className="error">{error}</div> : null}

      <div className="chatComposer">
        <textarea
          className="textarea"
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          placeholder="Send a message…"
          rows={3}
          onKeyDown={(e) => {
            if (e.key === 'Enter' && !e.shiftKey) {
              e.preventDefault()
              void onSend()
            }
          }}
        />
        <button className="button" disabled={!canSend} onClick={onSend}>
          {streaming ? 'Sending…' : 'Send'}
        </button>
      </div>
    </div>
  )
}



