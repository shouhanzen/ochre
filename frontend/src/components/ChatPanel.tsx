import { useEffect, useMemo, useRef, useState } from 'react'

import { getSession, type SessionMessage } from '../sessionApi'
import { SessionSocket, type WsFrame } from '../ws'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { type ChatMsg, parseToolPills, ToolList } from './ChatTools'
import { WidgetButtons, WidgetFile, WidgetSelect } from './Widgets'

function formatTokenCount(n: any): string {
  const num = Number(n)
  if (!Number.isFinite(num)) return ''
  if (num >= 1000) {
    return (num / 1000).toFixed(1) + 'k'
  }
  return String(num)
}

function formatChatTranscript(msgs: ChatMsg[]): string {
  const parts: string[] = []
  for (const it of groupRenderItems(msgs)) {
    if (it.kind === 'msg') {
      const m = it.msg
      const ts = m.ts ? ` [${m.ts}]` : ''
      const head = `${m.role.toUpperCase()}${ts}:`
      parts.push(`${head}\n${(m.content ?? '').trimEnd()}\n`)
      continue
    }
    // tools
    const toolLines = it.msgs.map((m) => (m.content ?? '').trimEnd()).filter(Boolean)
    if (toolLines.length) {
      parts.push(`TOOLS:\n${toolLines.join('\n')}\n`)
    }
  }
  return parts.join('\n').trimEnd()
}

async function writeClipboardTextWithFallback(text: string): Promise<boolean> {
  // Prefer modern clipboard API when available; it may fail on non-HTTPS contexts.
  try {
    if (typeof navigator !== 'undefined' && navigator.clipboard && typeof navigator.clipboard.writeText === 'function') {
      await navigator.clipboard.writeText(text)
      return true
    }
  } catch {
    // fall through to execCommand fallback
  }

  try {
    if (typeof document === 'undefined') return false
    const ta = document.createElement('textarea')
    ta.value = text
    ta.setAttribute('readonly', 'true')
    ta.style.position = 'fixed'
    ta.style.top = '0'
    ta.style.left = '0'
    ta.style.width = '1px'
    ta.style.height = '1px'
    ta.style.opacity = '0'
    document.body.appendChild(ta)
    ta.focus()
    ta.select()
    const ok = document.execCommand('copy')
    document.body.removeChild(ta)
    return ok
  } catch {
    return false
  }
}

function toChatMsgs(msgs: SessionMessage[]): ChatMsg[] {
  return msgs
    .filter((m) => {
      if (m.role !== 'user' && m.role !== 'assistant' && m.role !== 'system' && m.role !== 'tool') return false
      if (m.role === 'assistant' && (!m.content || !m.content.trim())) return false
      return true
    })
    .map((m) => {
      const meta = (m.meta ?? {}) as any
      const rid = typeof meta.requestId === 'string' ? meta.requestId : undefined
      return { id: m.id, role: m.role as any, content: m.content ?? '', ts: m.created_at, meta: meta ?? {}, requestId: rid }
    })
}

type RenderItem =
  | { kind: 'msg'; msg: ChatMsg; key: string }
  | { kind: 'tools'; msgs: ChatMsg[]; key: string }

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

function Markdown({ text, onSend }: { text: string; onSend: (t: string) => void }) {
  return (
    <ReactMarkdown
      remarkPlugins={[remarkGfm]}
      components={{
        a: (props) => <a {...props} target="_blank" rel="noreferrer" />,
        pre: (props) => <pre className="mdPre" {...props} />,
        code: ({ className, children, ...props }) => {
          const match = /language-widget:(\w+)/.exec(className || '')
          if (match) {
            const widgetType = match[1]
            try {
              const content = String(children).replace(/\n$/, '')
              const config = JSON.parse(content)
              if (widgetType === 'buttons') return <WidgetButtons config={config} onSend={onSend} />
              if (widgetType === 'select') return <WidgetSelect config={config} onSend={onSend} />
              if (widgetType === 'file') return <WidgetFile config={config} />
            } catch (e) {
              console.error('Widget parse error', e)
              return (
                <code className={`mdCode ${className ?? ''}`} {...props}>
                  {children}
                </code>
              )
            }
          }
          return (
            <code className={`mdCode ${className ?? ''}`} {...props}>
              {children}
            </code>
          )
        },
      }}
    >
      {text}
    </ReactMarkdown>
  )
}

import { ChatComposer } from './ChatComposer'

export function ChatPanel(props: { sessionId?: string; variant?: 'desktop' | 'mobile'; onNewConversation?: () => Promise<void> | void }) {
  const isMobile = props.variant === 'mobile'
  const [messages, setMessages] = useState<ChatMsg[]>([])
  const [streaming, setStreaming] = useState(false)
  const streamingRef = useRef(false)
  const [connecting, setConnecting] = useState(false)
  const [pending, setPending] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [sock, setSock] = useState<SessionSocket | null>(null)
  const [copied, setCopied] = useState(false)

  const chatLogRef = useRef<HTMLDivElement | null>(null)
  const shouldAutoScrollRef = useRef(true)

  const handleScroll = () => {
    if (!chatLogRef.current) return
    const { scrollTop, scrollHeight, clientHeight } = chatLogRef.current
    const isAtBottom = scrollHeight - scrollTop - clientHeight < 50
    shouldAutoScrollRef.current = isAtBottom
  }

  // Initial scroll to bottom on load
  useEffect(() => {
    shouldAutoScrollRef.current = true
    bottomRef.current?.scrollIntoView({ block: 'end' })
  }, [props.sessionId])

  const bottomRef = useRef<HTMLDivElement | null>(null)
  const streamingAssistantIdxRef = useRef<number | null>(null)
  const pendingIdxRef = useRef<number | null>(null)
  const activeRequestIdRef = useRef<string | null>(null)
  const pendingRequestIdRef = useRef<string | null>(null)
  const waitingForStartedRef = useRef<string | null>(null)
  const waitingForFirstTokenRef = useRef<string | null>(null)

  useEffect(() => {
    streamingRef.current = streaming
  }, [streaming])

  // Limit rendering to the last 10 messages (approx) to improve performance.
  // We use a simple slice, but we need to be careful not to split a tool group in half (visual glitch).
  // groupRenderItems handles grouping, so let's slice *after* grouping? 
  // Slicing after grouping is safer for tool groups.
  const allRenderItems = useMemo(() => groupRenderItems(messages), [messages])
  const renderedItems = useMemo(() => {
     if (allRenderItems.length <= 10) return allRenderItems
     return allRenderItems.slice(allRenderItems.length - 10)
  }, [allRenderItems])

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

        setMessages((prev) => {
          const serverRequestIds = new Set(chatMsgs.map((m) => m.requestId).filter(Boolean))
          const pending = prev.filter((m) => {
            if (m.role !== 'user') return false
            if (!m.requestId) return false
            if (serverRequestIds.has(m.requestId)) return false
            return true
          })
          return [...chatMsgs, ...pending]
        })
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
        if (shouldAutoScrollRef.current) {
            bottomRef.current?.scrollIntoView({ block: 'end' })
        }
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
      } else if (f.type === 'chat.usage') {
        const u = f.payload as any
        const rid = String(f.requestId ?? activeRequestIdRef.current ?? '')
        setMessages((prev) => {
          const copy = prev.slice()
          // Find the assistant message for this request (usually the last one)
          let idx = -1
          for (let i = copy.length - 1; i >= 0; i--) {
            if (copy[i].role === 'assistant' && copy[i].requestId === rid) {
              idx = i
              break
            }
          }
          if (idx >= 0) {
            const m = copy[idx]
            copy[idx] = { ...m, meta: { ...m.meta, usage: u } }
            return copy
          }
          return copy
        })
      } else if (f.type === 'tool.start') {
        const tool = String(f.payload?.tool ?? 'tool')
        const args = String(f.payload?.argsPreview ?? '')
        const tcId = f.payload?.tcId ? String(f.payload.tcId) : `tc-${Date.now()}-${Math.random()}`
        
        // Structured approach: use meta for everything, empty content
        setMessages((prev) => [
          ...prev,
          { 
            role: 'tool', 
            content: '', // content empty for structured tools
            ts: new Date().toISOString(), 
            requestId: String(f.requestId ?? activeRequestIdRef.current ?? ''), 
            kind: 'normal',
            meta: { 
              tool_call_id: tcId,
              name: tool,
              argsPreview: args
            }
          },
        ])
        if (shouldAutoScrollRef.current) {
            bottomRef.current?.scrollIntoView({ block: 'end' })
        }
      } else if (f.type === 'tool.end') {
        const tool = String(f.payload?.tool ?? 'tool')
        const ok = !!f.payload?.ok
        const ms = Number(f.payload?.durationMs ?? 0)
        const tcId = f.payload?.tcId ? String(f.payload.tcId) : null
        
        setMessages((prev) => {
          if (!tcId) return prev
          const copy = prev.slice()
          const idx = copy.findIndex(m => m.role === 'tool' && (m.meta as any)?.tool_call_id === tcId)
          if (idx >= 0) {
            copy[idx] = {
              ...copy[idx],
              meta: {
                ...copy[idx].meta,
                ok,
                durationMs: ms
              }
            }
            return copy
          }
          return prev
        })
        if (shouldAutoScrollRef.current) {
            bottomRef.current?.scrollIntoView({ block: 'end' })
        }
      } else if (f.type === 'tool.output') {
        const tool = String(f.payload?.tool ?? 'tool')
        // 'content' might be missing if backend sends 'output' key.
        const c = String(f.payload?.content ?? f.payload?.output ?? '')
        const tcId = f.payload?.tcId ? String(f.payload.tcId) : null
        
        // If we have a tcId, update the existing message. If not, append a new one (legacy fallback).
        if (tcId) {
             setMessages((prev) => {
              const copy = prev.slice()
              const idx = copy.findIndex(m => m.role === 'tool' && (m.meta as any)?.tool_call_id === tcId)
              if (idx >= 0) {
                // We store the output in the content field now, but keep the meta structure
                copy[idx] = {
                  ...copy[idx],
                  content: c
                }
                return copy
              }
              return prev
            })
        } else {
             // Fallback for legacy / untracked tools
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
        }
        if (shouldAutoScrollRef.current) {
            bottomRef.current?.scrollIntoView({ block: 'end' })
        }
      }
    })
    s.connect()
    setSock(s)
    return () => s.close()
  }, [props.sessionId])

  async function onSend(content: string) {
    if (streaming) return
    if (!props.sessionId) return
    setError(null)
    const requestId = crypto.randomUUID()
    const userMsg: ChatMsg = { role: 'user', content: content.trim(), ts: new Date().toISOString(), requestId }
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

  async function onCopyConversation() {
    setCopied(false)
    const text = formatChatTranscript(messages) || '(no conversation yet)'
    const ok = await writeClipboardTextWithFallback(text)
    if (ok) {
      setCopied(true)
      setTimeout(() => setCopied(false), 1200)
    } else {
      setCopied(false)
    }
  }

  return (
    <div className="panel">
      <div className="panelHeader">
        <div className="panelTitle">Chat</div>
        <div className="row">
          {props.onNewConversation ? (
            <button
              className="button secondary"
              title="New conversation"
              onClick={() => void props.onNewConversation?.()}
              style={{ padding: '6px 8px' }}
            >
              <span style={{ fontSize: '14px', lineHeight: 1 }}>＋</span>
            </button>
          ) : null}
          <button
            className="button secondary"
            disabled={!props.sessionId || messages.length === 0}
            onClick={() => void onCopyConversation()}
            title={copied ? 'Copied' : 'Copy conversation'}
            style={{ padding: '6px 8px' }}
          >
            <span style={{ fontSize: '14px', lineHeight: 1 }}>{copied ? '✓' : '⎘'}</span>
          </button>
        </div>
      </div>

      <div className="chatLog" ref={chatLogRef} onScroll={handleScroll}>
        {!props.sessionId ? <div className="muted">Initializing session…</div> : null}
        {messages.length === 0 ? (
          <div className="muted">Ask the agent to view/edit `/fs/todos/today.todo.md` or `/fs/mnt/workspace/...`.</div>
        ) : null}
        {messages.length > 0 && renderedItems.length < allRenderItems.length ? (
            <div className="muted" style={{ marginBottom: 10, textAlign: 'center' }}>
              (Showing last 10 items)
            </div>
        ) : null}
        {renderedItems.map((it) => {
          if (it.kind === 'msg') {
            const m = it.msg
            return (
              <div key={it.key} className={`chatLine ${m.role}`} data-kind={m.kind ?? 'normal'}>
                <div className="chatLineHeader">
                  <span className="chatRole">{m.role}</span>
                  {m.ts ? <span className="chatTs">{m.ts}</span> : null}
                  {(m.meta as any)?.usage ? (
                    <span className="muted" style={{ marginLeft: 'auto', fontSize: '11px' }}>
                      {formatTokenCount((m.meta as any).usage.total_tokens)} tokens
                    </span>
                  ) : null}
                </div>
                <div className="chatContent md">
                  <Markdown text={m.content} onSend={onSend} />
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
              <ToolList pills={pills} />
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

      <ChatComposer
        sessionId={props.sessionId}
        isMobile={isMobile}
        canSend={!streaming}
        streaming={streaming}
        onSend={onSend}
      />
    </div>
  )
}
