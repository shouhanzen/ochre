import { useEffect, useMemo, useRef, useState } from 'react'

import { getSession, type SessionMessage } from '../sessionApi'
import { SessionSocket, type WsFrame } from '../ws'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'

type ChatMsg = {
  id?: string
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
    .map((m) => {
      const meta = (m.meta ?? {}) as any
      const rid = typeof meta.requestId === 'string' ? meta.requestId : undefined
      return { id: m.id, role: m.role as any, content: m.content ?? '', ts: m.created_at, meta: meta ?? {}, requestId: rid }
    })
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

function makeUuidV4FromRandomBytes(bytes: Uint8Array): string {
  // RFC 4122 version 4 + variant bits
  bytes[6] = (bytes[6] & 0x0f) | 0x40
  bytes[8] = (bytes[8] & 0x3f) | 0x80
  const hex = Array.from(bytes, (b) => b.toString(16).padStart(2, '0')).join('')
  return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`
}

function safeRandomUUID(): { id: string; method: 'randomUUID' | 'getRandomValues' | 'fallback' } {
  const c = (globalThis as any).crypto as Crypto | undefined
  if (c && typeof (c as any).randomUUID === 'function') {
    return { id: (c as any).randomUUID(), method: 'randomUUID' }
  }
  if (c && typeof c.getRandomValues === 'function') {
    const bytes = new Uint8Array(16)
    c.getRandomValues(bytes)
    return { id: makeUuidV4FromRandomBytes(bytes), method: 'getRandomValues' }
  }
  // Last resort (not cryptographically strong): still unique enough for request correlation in UI.
  return { id: `r-${Date.now().toString(16)}-${Math.random().toString(16).slice(2)}-${Math.random().toString(16).slice(2)}`, method: 'fallback' }
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
  const streamingRef = useRef(false)
  const [connecting, setConnecting] = useState(false)
  const [pending, setPending] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [sock, setSock] = useState<SessionSocket | null>(null)

  const bottomRef = useRef<HTMLDivElement | null>(null)
  const streamingAssistantIdxRef = useRef<number | null>(null)
  const pendingIdxRef = useRef<number | null>(null)
  const activeRequestIdRef = useRef<string | null>(null)
  const pendingRequestIdRef = useRef<string | null>(null)
  const waitingForStartedRef = useRef<string | null>(null)
  const waitingForFirstTokenRef = useRef<string | null>(null)

  const canSend = useMemo(() => draft.trim().length > 0 && !streaming, [draft, streaming])

  useEffect(() => {
    streamingRef.current = streaming
  }, [streaming])

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
        waitingForStartedRef.current = null
        waitingForFirstTokenRef.current = null
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
      if (f.type !== 'system.message' && f.type !== 'snapshot') {
        if (activeRequestIdRef.current && f.requestId && f.requestId !== activeRequestIdRef.current) return
      }

      if (f.type === 'snapshot') {
        const view: any = f.payload ?? {}
        const msgs = Array.isArray(view.messages) ? view.messages : []
        let chatMsgs = toChatMsgs(msgs)

        const overlay = view?.overlays?.assistant
        if (overlay && typeof overlay.messageId === 'string' && typeof overlay.content === 'string') {
          const idx = chatMsgs.findIndex((m) => m.id === overlay.messageId)
          if (idx >= 0) {
            chatMsgs[idx] = { ...chatMsgs[idx], content: overlay.content }
          } else if (overlay.content.trim()) {
            // Fallback: if the DB message row isn't present yet, render the buffered assistant content as a normal bubble.
            chatMsgs.push({ role: 'assistant', content: overlay.content, ts: new Date().toISOString(), kind: 'normal' })
          }
        }

        setMessages(chatMsgs)
        const ar = view?.activeRun
        if (ar && ar.status === 'running' && typeof ar.requestId === 'string') {
          activeRequestIdRef.current = ar.requestId
          setStreaming(true)
          setConnecting(false)
          // If we have no assistant content yet, we're probably still in tools.
          const hasAssistant = !!(overlay && typeof overlay.content === 'string' && overlay.content.trim().length > 0)
          setPending(!hasAssistant)
        } else {
          setStreaming(false)
          setConnecting(false)
          setPending(false)
        }
        return
      }

      if (f.type === 'assistant.segment.started') {
        // No-op for now; deltas include messageId and we can place them precisely.
        return
      }

      if (f.type === 'chat.delta') {
        // first token => stop showing the "Running tools…" indicator
        if (pendingRequestIdRef.current && f.requestId === pendingRequestIdRef.current) {
          pendingRequestIdRef.current = null
          setPending(false)
        }
        if (waitingForFirstTokenRef.current && f.requestId === waitingForFirstTokenRef.current) {
          waitingForFirstTokenRef.current = null
        }
        setMessages((prev) => {
          const copy = prev.slice()
          const rid = String(f.requestId ?? activeRequestIdRef.current ?? '')
          const text = String(f.payload?.text ?? '')
          const mid = f.payload?.messageId ? String(f.payload?.messageId) : null

          // If the server provided a messageId, update that exact bubble.
          if (mid) {
            const j = copy.findIndex((m) => m.id === mid)
            if (j >= 0) {
              copy[j] = { ...copy[j], content: (copy[j].content ?? '') + text, requestId: rid }
              return copy
            }
          }

          // Simple rule: append to the most recent assistant bubble IF it is the most recent bubble for this request.
          const last = copy[copy.length - 1]
          if (last?.role === 'assistant' && last.requestId === rid) {
            copy[copy.length - 1] = { ...last, content: (last.content ?? '') + text }
            return copy
          }

          // Otherwise create a new assistant bubble segment (this enables true interleaving around tool bubbles).
          copy.push({ role: 'assistant', content: text, ts: new Date().toISOString(), kind: 'normal', requestId: rid, id: mid ?? undefined })
          return copy
        })
        bottomRef.current?.scrollIntoView({ block: 'end' })
      } else if (f.type === 'chat.started') {
        setStreaming(true)
        setConnecting(false)
        waitingForStartedRef.current = null
        waitingForFirstTokenRef.current = String(f.requestId ?? activeRequestIdRef.current ?? null)
        pendingRequestIdRef.current = String(f.requestId ?? activeRequestIdRef.current ?? null)
        setPending(true)
      } else if (f.type === 'chat.done') {
        setStreaming(false)
        setConnecting(false)
        streamingAssistantIdxRef.current = null
        pendingIdxRef.current = null
        activeRequestIdRef.current = null
        pendingRequestIdRef.current = null
        waitingForStartedRef.current = null
        waitingForFirstTokenRef.current = null
        setPending(false)
      } else if (f.type === 'chat.cancelled') {
        setStreaming(false)
        setConnecting(false)
        streamingAssistantIdxRef.current = null
        pendingIdxRef.current = null
        activeRequestIdRef.current = null
        pendingRequestIdRef.current = null
        waitingForStartedRef.current = null
        waitingForFirstTokenRef.current = null
        setPending(false)
        setMessages((prev) => [...prev, { role: 'system', content: 'Generation cancelled.', ts: new Date().toISOString() }])
      } else if (f.type === 'chat.error') {
        setStreaming(false)
        setConnecting(false)
        streamingAssistantIdxRef.current = null
        pendingIdxRef.current = null
        activeRequestIdRef.current = null
        pendingRequestIdRef.current = null
        waitingForStartedRef.current = null
        waitingForFirstTokenRef.current = null
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
      } else if (f.type === 'tool.output') {
        const tool = String(f.payload?.tool ?? 'tool')
        const c = String(f.payload?.content ?? '')
        const note = f.payload?.truncated ? '\n\n(truncated in live stream; reload to see full output)' : ''
        const line = c ? c + note : '(tool output)'
        setMessages((prev) => [
          ...prev,
          {
            role: 'tool',
            content: line,
            ts: new Date().toISOString(),
            requestId: String(f.requestId ?? activeRequestIdRef.current ?? ''),
            kind: 'normal',
            meta: { name: tool },
          },
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
    const { id: requestId } = safeRandomUUID()
    waitingForStartedRef.current = requestId
    waitingForFirstTokenRef.current = null
    activeRequestIdRef.current = requestId
    pendingIdxRef.current = null
    streamingAssistantIdxRef.current = null
    pendingRequestIdRef.current = requestId
    setConnecting(true)
    setPending(false)
    setMessages((prev) => [...prev, userMsg])

    // Instrument: if the PWA “sometimes doesn’t respond”, the usual culprit is no WS open / no server ack.
    // This log + timeout make it obvious which stage we got stuck at.
    console.info('[Ochre] chat.send', {
      requestId,
      contentLen: userMsg.content.length,
      ws: sock?.getDebugSnapshot?.(),
    })

    try {
      sock?.sendChat(userMsg.content, requestId)
    } catch (e: any) {
      console.error('[Ochre] sendChat threw', { requestId, err: e?.message ?? String(e), ws: sock?.getDebugSnapshot?.() })
      setError(e?.message ?? String(e))
      setConnecting(false)
      setPending(false)
      waitingForStartedRef.current = null
      return
    }

    // If we don't get chat.started quickly, capture a snapshot (mobile networks sometimes stall CONNECTING forever).
    window.setTimeout(() => {
      if (waitingForStartedRef.current !== requestId) return
      console.warn('[Ochre] chat.started timeout', { requestId, ws: sock?.getDebugSnapshot?.() })
    }, 8000)

    // If we started but never got first token, capture that separately.
    window.setTimeout(() => {
      if (!streamingRef.current) return
      if (waitingForFirstTokenRef.current !== requestId) return
      console.warn('[Ochre] first token timeout', { requestId, ws: sock?.getDebugSnapshot?.() })
    }, 25_000)
  }

  return (
    <div className="panel">
      <div className="panelHeader">
        <div className="panelTitle">Chat</div>
        <div className="muted">Backend default model</div>
      </div>

      <div className="chatLog">
        {!props.sessionId ? <div className="muted">Initializing session…</div> : null}
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
        {connecting ? (
          <div className="chatLine assistant" data-kind="pending">
            <div className="chatLineHeader">
              <span className="chatRole">assistant</span>
            </div>
            <div className="chatContent">Connecting…</div>
          </div>
        ) : null}
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
          placeholder={props.sessionId ? 'Send a message…' : 'Waiting for session…'}
          rows={3}
          onKeyDown={(e) => {
            if (e.key === 'Enter' && !e.shiftKey) {
              e.preventDefault()
              void onSend()
            }
          }}
          disabled={!props.sessionId}
        />
        <button className="button" disabled={!props.sessionId || !canSend} onClick={onSend}>
          {streaming ? 'Sending…' : 'Send'}
        </button>
      </div>
    </div>
  )
}



