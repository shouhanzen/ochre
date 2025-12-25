import { useEffect, useState } from 'react'

async function jsonFetch<T>(path: string): Promise<T> {
  const res = await fetch(path)
  if (!res.ok) throw new Error(await res.text())
  return (await res.json()) as T
}

export function StatusBar(props: { sessionId?: string }) {
  const [model, setModel] = useState<string>('…')
  const [pendingCount, setPendingCount] = useState<number>(0)
  const [backendOk, setBackendOk] = useState<boolean>(true)

  useEffect(() => {
    ;(async () => {
      try {
        const res = await jsonFetch<{ defaultModel: string }>('/api/settings')
        setModel(res.defaultModel)
      } catch {
        setModel('default')
      }
    })()
  }, [])

  useEffect(() => {
    const interval = setInterval(() => {
      ;(async () => {
        try {
          const res = await jsonFetch<{ pending: unknown[] }>('/api/kanban/pending')
          setPendingCount((res.pending ?? []).length)
        } catch {
          setPendingCount(0)
        }
        try {
          const res = await jsonFetch<{ ok: boolean }>('/api/health')
          setBackendOk(!!res.ok)
        } catch {
          setBackendOk(false)
        }
      })()
    }, 4000)
    return () => clearInterval(interval)
  }, [])

  const sid = props.sessionId ? props.sessionId.slice(0, 8) : '…'

  return (
    <div className="statusBar">
      <span>Session: {sid}</span>
      <span className="spacer" />
      <span>Model: {model}</span>
      <span>Pending: {pendingCount}</span>
      <span>{backendOk ? '●' : '○'} Backend</span>
    </div>
  )
}


