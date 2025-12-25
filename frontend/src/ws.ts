export type WsFrame =
  | { type: 'chat.started'; requestId: string | null; payload: { messageId: string } }
  | { type: 'chat.delta'; requestId: string | null; payload: { text: string } }
  | { type: 'chat.done'; requestId: string | null; payload: { ok: boolean } }
  | { type: 'chat.cancelled'; requestId: string | null; payload: { reason: string } }
  | { type: 'chat.error'; requestId: string | null; payload: { message: string } }
  | { type: 'tool.start'; requestId: string | null; payload: { tool: string; argsPreview: string } }
  | { type: 'tool.end'; requestId: string | null; payload: { tool: string; ok: boolean; durationMs: number } }
  | { type: 'system.message'; requestId: string | null; payload: { content: string } }
  | { type: string; requestId: string | null; payload: any }

export class SessionSocket {
  private ws: WebSocket | null = null
  private sessionId: string
  private onFrame: (f: WsFrame) => void
  private queue: string[] = []

  constructor(sessionId: string, onFrame: (f: WsFrame) => void) {
    this.sessionId = sessionId
    this.onFrame = onFrame
  }

  connect() {
    if (this.ws && (this.ws.readyState === WebSocket.OPEN || this.ws.readyState === WebSocket.CONNECTING)) return
    const proto = window.location.protocol === 'https:' ? 'wss' : 'ws'
    const url = `${proto}://${window.location.host}/ws/sessions/${encodeURIComponent(this.sessionId)}`
    this.ws = new WebSocket(url)
    this.ws.onopen = () => {
      // flush queued messages
      const q = this.queue.splice(0, this.queue.length)
      for (const payload of q) {
        try {
          this.ws?.send(payload)
        } catch {
          // drop if still failing
        }
      }
    }
    this.ws.onmessage = (ev) => {
      try {
        this.onFrame(JSON.parse(ev.data))
      } catch {
        // ignore
      }
    }
    this.ws.onclose = () => {
    }
  }

  close() {
    try {
      this.ws?.close()
    } catch {
      // ignore
    }
    this.ws = null
  }

  sendChat(content: string, requestId: string) {
    this.connect()
    const rs = this.ws?.readyState
    const payload = JSON.stringify({ type: 'chat.send', requestId, payload: { content } })
    try {
      if (rs === WebSocket.OPEN) {
        this.ws?.send(payload)
        return
      }
      // queue until open (covers CONNECTING)
      this.queue.push(payload)
      return
    } catch (e: any) {
      throw e
    }
  }
}


