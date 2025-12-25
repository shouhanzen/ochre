import { useEffect, useState } from 'react'
import { fsList, type FileEntry } from '../api'

type Root = { label: string; path: string }

async function listPath(path: string): Promise<FileEntry[]> {
  return (await fsList(path)).entries
}

export function FileTree(props: { onSelectFile: (path: string) => void; selectedPath?: string }) {
  const [roots, setRoots] = useState<Root[]>([])

  const [expanded, setExpanded] = useState<Record<string, boolean>>({})
  const [children, setChildren] = useState<Record<string, FileEntry[]>>({})
  const [error, setError] = useState<string | null>(null)

  async function ensureLoaded(path: string) {
    if (children[path]) return
    try {
      setError(null)
      const entries = await listPath(path)
      setChildren((prev) => ({ ...prev, [path]: entries }))
    } catch (e: any) {
      setError(e?.message ?? String(e))
    }
  }

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
        for (const r of discovered) {
          void ensureLoaded(r.path)
          setExpanded((prev) => ({ ...prev, [r.path]: true }))
        }
      } catch (e: any) {
        setError(e?.message ?? String(e))
        // fallback roots if /fs discovery fails
        const fallback: Root[] = [
          { label: 'todos', path: '/fs/todos' },
          { label: 'mnt', path: '/fs/mnt' },
        ]
        setRoots(fallback)
        for (const r of fallback) {
          void ensureLoaded(r.path)
          setExpanded((prev) => ({ ...prev, [r.path]: true }))
        }
      }
    })()
  }, [])

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
