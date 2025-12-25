export type Session = {
  id: string
  title: string | null
  created_at: string
  last_active_at: string
}

export type SessionMessage = {
  id: string
  session_id: string
  role: 'user' | 'assistant' | 'system' | 'tool'
  content: string | null
  created_at: string
  meta: Record<string, unknown>
}

async function jsonFetch<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(path, {
    ...init,
    headers: {
      'Content-Type': 'application/json',
      ...(init?.headers ?? {}),
    },
  })
  if (!res.ok) {
    const text = await res.text()
    throw new Error(text || `HTTP ${res.status}`)
  }
  return (await res.json()) as T
}

export async function createSession(body: { title: string | null }): Promise<{ session: Session }> {
  return await jsonFetch('/api/sessions', { method: 'POST', body: JSON.stringify(body) })
}

export async function listSessions(limit = 50): Promise<{ sessions: Session[] }> {
  return await jsonFetch(`/api/sessions?limit=${limit}`)
}

export async function getSession(
  sessionId: string,
  limit = 200,
): Promise<{ session: Session; messages: SessionMessage[] }> {
  return await jsonFetch(`/api/sessions/${encodeURIComponent(sessionId)}?limit=${limit}`)
}

export async function streamSessionChat(opts: {
  sessionId: string
  content: string
  model?: string
  onDelta: (text: string) => void
}): Promise<void> {
  const res = await fetch(`/api/sessions/${encodeURIComponent(opts.sessionId)}/chat`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ content: opts.content, model: opts.model ?? null }),
  })
  if (!res.ok || !res.body) throw new Error(await res.text())

  const decoder = new TextDecoder()
  const reader = res.body.getReader()
  let buffer = ''

  while (true) {
    const { done, value } = await reader.read()
    if (done) break
    buffer += decoder.decode(value, { stream: true })
    while (true) {
      const idx = buffer.indexOf('\n\n')
      if (idx === -1) break
      const eventBlock = buffer.slice(0, idx)
      buffer = buffer.slice(idx + 2)

      let event = 'message'
      let dataStr = ''
      for (const line of eventBlock.split('\n')) {
        if (line.startsWith('event:')) event = line.slice('event:'.length).trim()
        if (line.startsWith('data:')) dataStr += line.slice('data:'.length).trim()
      }
      if (!dataStr) continue
      const data = JSON.parse(dataStr) as any
      if (event === 'delta') opts.onDelta(String(data.text ?? ''))
      if (event === 'error') throw new Error(String(data.message ?? 'Chat error'))
    }
  }
}

export function subscribeSessionEvents(sessionId: string, onEvent: (ev: any) => void): () => void {
  const es = new EventSource(`/api/sessions/${encodeURIComponent(sessionId)}/events`)
  es.addEventListener('event', (e: MessageEvent) => {
    try {
      onEvent(JSON.parse(e.data))
    } catch {
      onEvent({ raw: e.data })
    }
  })
  es.addEventListener('error', () => {
    // keep it quiet; EventSource will retry
  })
  return () => es.close()
}


