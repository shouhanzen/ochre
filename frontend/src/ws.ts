import type { SessionMessage } from './sessionApi'

export type WsFrame =
  | { type: 'hello'; requestId: string | null; payload: { lastSeq?: number | null } }
  | {
      type: 'snapshot'
      requestId: string | null
      payload: {
        sessionId: string
        messages: SessionMessage[]
        activeRun?: { requestId: string; status: string; startedAt: string; endedAt?: string | null; model?: string | null } | null
        overlays?: { assistant?: { messageId: string; content: string } } | null
        lastSeq?: number | null
      }
    }
  | { type: 'chat.started'; requestId: string | null; payload: { messageId?: string | null } }
  | { type: 'assistant.segment.started'; requestId: string | null; payload: { messageId: string } }
  | { type: 'chat.delta'; requestId: string | null; payload: { text: string; messageId?: string | null } }
  | { type: 'chat.done'; requestId: string | null; payload: { ok: boolean } }
  | { type: 'chat.cancelled'; requestId: string | null; payload: { reason: string } }
  | { type: 'chat.error'; requestId: string | null; payload: { message: string } }
  | { type: 'tool.start'; requestId: string | null; payload: { tool: string; argsPreview: string } }
  | { type: 'tool.end'; requestId: string | null; payload: { tool: string; ok: boolean; durationMs: number } }
  | { type: 'tool.output'; requestId: string | null; payload: { tool: string; content: string; truncated?: boolean } }
  | { type: 'system.message'; requestId: string | null; payload: { content: string } }
  | { type: string; requestId: string | null; payload: any }

type NetInfo = {
  online: boolean | null
  visibility: 'visible' | 'hidden' | null
  effectiveType?: string | null
  rttMs?: number | null
  downlinkMbps?: number | null
  saveData?: boolean | null
}

function nowIso() {
  return new Date().toISOString()
}

function safeNetInfo(): NetInfo {
  const online = typeof navigator !== 'undefined' && 'onLine' in navigator ? !!navigator.onLine : null
  const visibility =
    typeof document !== 'undefined' && typeof document.visibilityState === 'string'
      ? (document.visibilityState as any)
      : null

  const c = (navigator as any)?.connection
  const out: NetInfo = { online, visibility }
  if (c && typeof c === 'object') {
    out.effectiveType = typeof c.effectiveType === 'string' ? c.effectiveType : null
    out.rttMs = typeof c.rtt === 'number' ? c.rtt : null
    out.downlinkMbps = typeof c.downlink === 'number' ? c.downlink : null
    out.saveData = typeof c.saveData === 'boolean' ? c.saveData : null
  }
  return out
}

function wsStateLabel(rs: number | null | undefined): string {
  if (rs === WebSocket.CONNECTING) return 'CONNECTING'
  if (rs === WebSocket.OPEN) return 'OPEN'
  if (rs === WebSocket.CLOSING) return 'CLOSING'
  if (rs === WebSocket.CLOSED) return 'CLOSED'
  return 'NONE'
}

function isWsDebugEnabled(): boolean {
  try {
    const url = new URL(window.location.href)
    const q = url.searchParams.get('debugWs') ?? url.searchParams.get('debug')
    if (q === '1' || q === 'true') return true
  } catch {
    // ignore
  }
  try {
    return localStorage.getItem('ochre.debugWs') === '1'
  } catch {
    return false
  }
}

export class SessionSocket {
  private ws: WebSocket | null = null
  private sessionId: string
  private onFrame: (f: WsFrame) => void
  private queue: string[] = []

  private url: string | null = null
  private closedByUser = false
  private connectAttempt = 0
  private reconnectAttempt = 0
  private reconnectTimer: number | null = null
  private connectTimeoutTimer: number | null = null
  private lastConnectStartMs: number | null = null
  private lastOpenAt: string | null = null
  private lastCloseAt: string | null = null
  private lastErrorAt: string | null = null
  private lastMessageAt: string | null = null
  private lastSendAt: string | null = null
  private lastClose: { code?: number; reason?: string; wasClean?: boolean } | null = null

  private debug: boolean
  private boundOnline?: () => void
  private boundVisibility?: () => void

  constructor(sessionId: string, onFrame: (f: WsFrame) => void, opts?: { debug?: boolean }) {
    this.sessionId = sessionId
    this.onFrame = onFrame
    this.debug = opts?.debug ?? isWsDebugEnabled()
  }

  private log(level: 'debug' | 'info' | 'warn' | 'error', msg: string, detail?: any) {
    // Keep the signal high, but ensure we still get useful timelines even when debugWs is off.
    if (!this.debug && level === 'debug') return
    const base = {
      ts: nowIso(),
      sessionId: this.sessionId,
      url: this.url,
      rs: wsStateLabel(this.ws?.readyState ?? null),
      queue: this.queue.length,
      net: safeNetInfo(),
      ...detail,
    }
    const fn = (console as any)[level]?.bind(console) ?? console.log.bind(console)
    fn(`[Ochre WS] ${msg}`, base)
  }

  getDebugSnapshot() {
    return {
      ts: nowIso(),
      sessionId: this.sessionId,
      url: this.url,
      readyState: this.ws?.readyState ?? null,
      readyStateLabel: wsStateLabel(this.ws?.readyState ?? null),
      queueSize: this.queue.length,
      connectAttempt: this.connectAttempt,
      reconnectAttempt: this.reconnectAttempt,
      lastOpenAt: this.lastOpenAt,
      lastCloseAt: this.lastCloseAt,
      lastErrorAt: this.lastErrorAt,
      lastMessageAt: this.lastMessageAt,
      lastSendAt: this.lastSendAt,
      lastClose: this.lastClose,
      net: safeNetInfo(),
    }
  }

  private installEnvListeners() {
    if (this.boundOnline || this.boundVisibility) return
    this.boundOnline = () => {
      this.log('info', 'online event')
      if (!this.closedByUser && this.queue.length > 0) this.connect('online')
    }
    this.boundVisibility = () => {
      const v = safeNetInfo().visibility
      this.log('info', 'visibilitychange', { visibility: v })
      if (v === 'visible' && !this.closedByUser && this.queue.length > 0) this.connect('visible')
    }
    window.addEventListener('online', this.boundOnline)
    document.addEventListener('visibilitychange', this.boundVisibility)
  }

  private clearTimers() {
    if (this.reconnectTimer != null) {
      window.clearTimeout(this.reconnectTimer)
      this.reconnectTimer = null
    }
    if (this.connectTimeoutTimer != null) {
      window.clearTimeout(this.connectTimeoutTimer)
      this.connectTimeoutTimer = null
    }
  }

  private scheduleReconnect(reason: string) {
    if (this.closedByUser) return
    if (this.reconnectTimer != null) return

    const base = 450
    const cap = 12_000
    const exp = Math.min(cap, base * Math.pow(2, Math.min(this.reconnectAttempt, 5)))
    const jitter = Math.round(Math.random() * 250)
    const delay = exp + jitter
    this.reconnectAttempt += 1
    this.log('warn', 'scheduling reconnect', { reason, delayMs: delay, reconnectAttempt: this.reconnectAttempt })
    this.reconnectTimer = window.setTimeout(() => {
      this.reconnectTimer = null
      // Only reconnect if we have something to do; avoids keeping a socket alive forever on flaky mobile.
      if (this.queue.length === 0) {
        this.log('debug', 'reconnect skipped (no queued messages)', { reason })
        return
      }
      this.connect(`reconnect:${reason}`)
    }, delay)
  }

  connect(reason = 'manual') {
    this.installEnvListeners()

    const rs = this.ws?.readyState
    if (rs === WebSocket.OPEN) return
    if (rs === WebSocket.CONNECTING) {
      // Guard against “stuck connecting” on mobile: if it takes too long, reset and retry.
      const started = this.lastConnectStartMs ?? Date.now()
      const elapsed = Date.now() - started
      if (elapsed < 10_000) return
      this.log('warn', 'connect stuck; resetting socket', { reason, elapsedMs: elapsed })
      try {
        this.ws?.close()
      } catch {
        // ignore
      }
      this.ws = null
    }

    this.clearTimers()
    this.closedByUser = false
    const proto = window.location.protocol === 'https:' ? 'wss' : 'ws'
    const url = `${proto}://${window.location.host}/ws/sessions/${encodeURIComponent(this.sessionId)}`
    this.url = url
    this.connectAttempt += 1
    this.lastConnectStartMs = Date.now()
    this.log('info', 'connect', { reason, connectAttempt: this.connectAttempt })
    this.ws = new WebSocket(url)

    // If connect doesn’t succeed quickly, force a reset to unstick (mobile radios / captive portals).
    this.connectTimeoutTimer = window.setTimeout(() => {
      if (!this.ws) return
      if (this.ws.readyState === WebSocket.CONNECTING) {
        this.log('warn', 'connect timeout; closing socket', { reason })
        try {
          this.ws.close()
        } catch {
          // ignore
        }
      }
    }, 12_000)

    this.ws.onopen = () => {
      this.clearTimers()
      this.reconnectAttempt = 0
      this.lastOpenAt = nowIso()
      this.log('info', 'open')
      // flush queued messages
      const q = this.queue.splice(0, this.queue.length)
      for (const payload of q) {
        try {
          this.ws?.send(payload)
        } catch {
          // drop if still failing
        }
      }
      if (q.length > 0) this.log('info', 'flushed queued messages', { flushed: q.length })

      // Ask server for a snapshot so we can resync after reconnect.
      try {
        this.ws?.send(JSON.stringify({ type: 'hello', requestId: null, payload: {} }))
        this.log('debug', 'sent hello')
      } catch {
        // ignore
      }
    }
    this.ws.onmessage = (ev) => {
      this.lastMessageAt = nowIso()
      try {
        this.onFrame(JSON.parse(ev.data))
      } catch {
        this.log('warn', 'message parse failed', { sample: String(ev.data ?? '').slice(0, 220) })
      }
    }
    this.ws.onerror = () => {
      this.lastErrorAt = nowIso()
      this.log('warn', 'error')
    }
    this.ws.onclose = (ev) => {
      this.clearTimers()
      this.lastCloseAt = nowIso()
      this.lastClose = { code: ev.code, reason: ev.reason, wasClean: ev.wasClean }
      this.log('warn', 'close', { code: ev.code, reason: ev.reason, wasClean: ev.wasClean })
      this.ws = null
      if (this.queue.length > 0) this.scheduleReconnect('close')
    }
  }

  close() {
    this.closedByUser = true
    this.clearTimers()
    try {
      this.ws?.close()
    } catch {
      // ignore
    }
    this.ws = null
    if (this.boundOnline) window.removeEventListener('online', this.boundOnline)
    if (this.boundVisibility) document.removeEventListener('visibilitychange', this.boundVisibility)
    this.boundOnline = undefined
    this.boundVisibility = undefined
  }

  sendChat(content: string, requestId: string) {
    this.connect('sendChat')
    const rs = this.ws?.readyState
    const payload = JSON.stringify({ type: 'chat.send', requestId, payload: { content } })
    try {
      this.lastSendAt = nowIso()
      if (rs === WebSocket.OPEN) {
        this.ws?.send(payload)
        this.log('debug', 'sent chat.send', { requestId, contentLen: content.length })
        return
      }
      // queue until open (covers CONNECTING)
      this.queue.push(payload)
      this.log('warn', 'queued chat.send (socket not open)', { requestId, contentLen: content.length })
      return
    } catch (e: any) {
      this.log('error', 'sendChat threw', { requestId, err: String(e?.message ?? e) })
      throw e
    }
  }
}


