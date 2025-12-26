export type DebugLevel = 'log' | 'info' | 'warn' | 'error' | 'debug'

export type DebugEntry = {
  ts: string
  level: DebugLevel
  message: string
  detail?: string
}

type Listener = (entries: DebugEntry[]) => void

const MAX_ENTRIES = 800

let installed = false
let entries: DebugEntry[] = []
const listeners = new Set<Listener>()

function nowIso() {
  return new Date().toISOString()
}

function safeToString(x: unknown): string {
  if (x == null) return String(x)
  if (typeof x === 'string') return x
  if (typeof x === 'number' || typeof x === 'boolean' || typeof x === 'bigint') return String(x)
  if (x instanceof Error) {
    const msg = x.message || String(x)
    const stack = x.stack ? `\n${x.stack}` : ''
    return `${x.name}: ${msg}${stack}`
  }
  try {
    const seen = new WeakSet<object>()
    return JSON.stringify(
      x,
      (_k, v) => {
        if (v instanceof Error) return { name: v.name, message: v.message, stack: v.stack }
        if (typeof v === 'object' && v !== null) {
          if (seen.has(v)) return '[Circular]'
          seen.add(v)
        }
        return v
      },
      2,
    )
  } catch {
    return String(x)
  }
}

function push(level: DebugLevel, args: unknown[], detail?: string) {
  const msg = args.map(safeToString).join(' ')
  const e: DebugEntry = { ts: nowIso(), level, message: msg, detail }
  entries = entries.length >= MAX_ENTRIES ? [...entries.slice(1), e] : [...entries, e]
  for (const l of listeners) l(entries)
}

export function getDebugEntries(): DebugEntry[] {
  return entries
}

export function clearDebugEntries() {
  entries = []
  for (const l of listeners) l(entries)
}

export function subscribeDebugEntries(listener: Listener) {
  listeners.add(listener)
  listener(entries)
  return () => {
    listeners.delete(listener)
  }
}

export function installDebugCapture() {
  if (installed) return
  installed = true

  const c = console as any
  const wrap = (level: DebugLevel) => {
    const orig = c[level]?.bind(console)
    c[level] = (...args: unknown[]) => {
      push(level, args)
      orig?.(...args)
    }
  }

  wrap('log')
  wrap('info')
  wrap('warn')
  wrap('error')
  wrap('debug')

  window.addEventListener('error', (ev) => {
    const err = (ev as ErrorEvent).error
    const msg = (ev as ErrorEvent).message || 'window.error'
    const loc = `${(ev as ErrorEvent).filename || ''}:${(ev as ErrorEvent).lineno || ''}:${(ev as ErrorEvent).colno || ''}`
    push('error', [msg], `${loc}\n${safeToString(err)}`)
  })

  window.addEventListener('unhandledrejection', (ev) => {
    push('error', ['Unhandled promise rejection'], safeToString((ev as PromiseRejectionEvent).reason))
  })
}

