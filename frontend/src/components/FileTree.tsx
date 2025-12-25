import { useCallback, useEffect, useRef, useState } from 'react'
import { fsList, type FileEntry } from '../api'

type Root = { label: string; path: string }
type ExpandedState = Record<string, boolean>

async function listPath(path: string): Promise<FileEntry[]> {
  return (await fsList(path)).entries
}

export function FileTree(props: { onSelectFile: (path: string) => void; selectedPath?: string }) {
  const [roots, setRoots] = useState<Root[]>([])

  const STORAGE_KEY = 'ochre.fileTree.expanded'
  const [expanded, setExpanded] = useState<ExpandedState>(() => {
    try {
      const raw = localStorage.getItem(STORAGE_KEY)
      if (!raw) return {}
      const parsed: unknown = JSON.parse(raw)
      if (!parsed || typeof parsed !== 'object') return {}
      const out: ExpandedState = {}
      for (const [k, v] of Object.entries(parsed as Record<string, unknown>)) {
        if (typeof k === 'string' && typeof v === 'boolean') out[k] = v
      }
      return out
    } catch {
      return {}
    }
  })
  const [children, setChildren] = useState<Record<string, FileEntry[]>>({})
  const [error, setError] = useState<string | null>(null)
  const childrenRef = useRef<Record<string, FileEntry[]>>({})
  const expandedRef = useRef<ExpandedState>({})

  useEffect(() => {
    childrenRef.current = children
  }, [children])
  useEffect(() => {
    expandedRef.current = expanded
  }, [expanded])

  useEffect(() => {
    try {
      const compact: Record<string, boolean> = {}
      for (const [k, v] of Object.entries(expanded)) {
        if (v) compact[k] = true
      }
      localStorage.setItem(STORAGE_KEY, JSON.stringify(compact))
    } catch {
      // ignore
    }
  }, [expanded])

  const ensureLoaded = useCallback(async (path: string) => {
    if (childrenRef.current[path]) return
    try {
      setError(null)
      const entries = await listPath(path)
      setChildren((prev) => ({ ...prev, [path]: entries }))
    } catch (e: unknown) {
      const err = e as { message?: string }
      setError(err?.message ?? String(e))
    }
  }, [])

  function toggleDir(path: string) {
    setExpanded((prev) => ({ ...prev, [path]: !prev[path] }))
  }

  useEffect(() => {
    ;(async () => {
      try {
        setError(null)
        const entries = await listPath('/fs')
        const discovered: Root[] = entries
          .filter((e) => e.kind === 'dir')
          .map((e) => ({ label: e.name, path: e.path }))
        setRoots(discovered)
        // Ensure roots are expanded by default only if the user hasn't persisted a preference yet.
        setExpanded((prev) => {
          const next = { ...prev }
          for (const r of discovered) {
            if (typeof next[r.path] !== 'boolean') next[r.path] = true
          }
          return next
        })
        for (const r of discovered) {
          void ensureLoaded(r.path)
        }
        // Load children for any persisted expanded directories (beyond roots).
        for (const [p, isExpanded] of Object.entries(expandedRef.current)) {
          if (isExpanded) void ensureLoaded(p)
        }
      } catch (e: unknown) {
        const err = e as { message?: string }
        setError(err?.message ?? String(e))
        // fallback roots if /fs discovery fails
        const fallback: Root[] = [
          { label: 'todos', path: '/fs/todos' },
          { label: 'mnt', path: '/fs/mnt' },
        ]
        setRoots(fallback)
        setExpanded((prev) => {
          const next = { ...prev }
          for (const r of fallback) {
            if (typeof next[r.path] !== 'boolean') next[r.path] = true
          }
          return next
        })
        for (const r of fallback) {
          void ensureLoaded(r.path)
        }
        for (const [p, isExpanded] of Object.entries(expandedRef.current)) {
          if (isExpanded) void ensureLoaded(p)
        }
      }
    })()
  }, [ensureLoaded])

  function renderDir(path: string, indent: number) {
    const entries = children[path] ?? []
    return (
      <div>
        {entries.map((e) => {
          const isDir = e.kind === 'dir'
          const isExpanded = !!expanded[e.path]
          const isSelected = props.selectedPath === e.path
          return (
            <div key={e.path}>
              <div
                className={isSelected ? 'treeRow selected' : 'treeRow'}
                style={{ paddingLeft: `${indent * 12}px` }}
                onClick={() => {
                  if (isDir) {
                    void ensureLoaded(e.path)
                    toggleDir(e.path)
                  } else {
                    props.onSelectFile(e.path)
                  }
                }}
              >
                <span className="treeIcon">{isDir ? (isExpanded ? '▾' : '▸') : '•'}</span>
                <span className="treeName">{e.name}</span>
              </div>
              {isDir && isExpanded ? renderDir(e.path, indent + 1) : null}
            </div>
          )
        })}
      </div>
    )
  }

  return (
    <div className="panel">
      <div className="panelHeader">
        <div className="panelTitle">Files</div>
        <div className="muted">Unified FS</div>
      </div>
      {error ? <div className="error">{error}</div> : null}

      <div className="tree">
        {roots.map((r) => (
          <div key={r.path}>
            <div
              className="treeRow root"
              onClick={() => {
                void ensureLoaded(r.path)
                toggleDir(r.path)
              }}
            >
              <span className="treeIcon">{expanded[r.path] ? '▾' : '▸'}</span>
              <span className="treeName">{r.label}</span>
            </div>
            {expanded[r.path] ? renderDir(r.path, 1) : null}
          </div>
        ))}
      </div>
    </div>
  )
}
