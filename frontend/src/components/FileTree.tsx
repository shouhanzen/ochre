import { useCallback, useEffect, useRef, useState } from 'react'
import { TreeCopyModal } from './TreeCopyModal'
import { fsList, fsMove, fsTree, type FileEntry } from '../api'

type Root = { label: string; path: string }
type ExpandedState = Record<string, boolean>

function useLongPress(callback: (e: React.MouseEvent | React.TouchEvent) => void, ms = 500) {
  const timeout = useRef<ReturnType<typeof setTimeout>>(undefined)
  const target = useRef<EventTarget | null>(null)

  const start = useCallback(
    (e: React.MouseEvent | React.TouchEvent) => {
      if ('persist' in e) (e as any).persist()
      if (timeout.current) clearTimeout(timeout.current)
      target.current = e.target
      timeout.current = setTimeout(() => {
        // Prevent native context menu if this was a touch event
        if ('touches' in e && e.target && (e.target as HTMLElement).blur) {
            (e.target as HTMLElement).blur()
        }
        callback(e)
      }, ms)
    },
    [callback, ms],
  )

  const clear = useCallback(() => {
    if (timeout.current) clearTimeout(timeout.current)
  }, [])

  return {
    onMouseDown: start,
    onTouchStart: start,
    onMouseUp: clear,
    onMouseLeave: clear,
    onTouchEnd: clear,
  }
}

function FileTreeRow(props: {
  entry: FileEntry
  indent: number
  isExpanded: boolean
  isSelected: boolean
  onToggle: (path: string) => void
  onSelect: (path: string) => void
  onOpen: (path: string) => void
  onContextMenu: (x: number, y: number, path: string) => void
  isRoot?: boolean
  children?: React.ReactNode
}) {
  const { entry: e, indent, isExpanded, isSelected, onToggle, onSelect, onOpen, onContextMenu, isRoot } = props
  const isDir = e.kind === 'dir'

  const lp = useLongPress((ev) => {
    const clientX = 'touches' in ev ? ev.touches[0].clientX : (ev as React.MouseEvent).clientX
    const clientY = 'touches' in ev ? ev.touches[0].clientY : (ev as React.MouseEvent).clientY
    // Prevent iOS text selection menu
    if ('touches' in ev) {
        ev.preventDefault()
    }
    onContextMenu(clientX, clientY, e.path)
  })

  return (
    <div>
      <div
        className={`treeRow${isSelected ? ' selected' : ''}${isRoot ? ' root' : ''}`}
        style={{ paddingLeft: `${indent * 12}px`, WebkitUserSelect: 'none', userSelect: 'none' }}
        onClick={() => {
          if (isDir) onToggle(e.path)
          else onSelect(e.path)
        }}
        onDoubleClick={() => {
          if (!isDir) onOpen(e.path)
        }}
        {...lp}
        onContextMenu={(ev) => {
          ev.preventDefault()
          onContextMenu(ev.clientX, ev.clientY, e.path)
        }}
      >
        <span className="treeIcon">{isDir ? (isExpanded ? '▾' : '▸') : '•'}</span>
        <span className="treeName">{e.name}</span>
      </div>
      {props.children}
    </div>
  )
}

export function FileTree(props: {
  onSelectFile: (path: string) => void
  onOpenFile?: (path: string) => void
  selectedPath?: string
}) {
  const [roots, setRoots] = useState<Root[]>([])
  const [contextMenu, setContextMenu] = useState<{ x: number; y: number; path: string } | null>(null)
  const [treeCopyPath, setTreeCopyPath] = useState<string | null>(null)


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
      const entries = (await fsList(path)).entries
      setChildren((prev) => ({ ...prev, [path]: entries }))
    } catch (e: unknown) {
      const err = e as { message?: string }
      setError(err?.message ?? String(e))
    }
  }, [])

  function toggleDir(path: string) {
    setExpanded((prev) => ({ ...prev, [path]: !prev[path] }))
  }

  async function handleRename(path: string) {
    setContextMenu(null)
    const name = path.split('/').pop() || ''
    const newName = window.prompt('Rename to:', name)
    if (!newName || newName === name) return

    const parts = path.split('/')
    parts.pop()
    const parent = parts.join('/')
    const newPath = `${parent}/${newName}`

    try {
      await fsMove(path, newPath)
      // Refresh parent
      const parentPath = parent || '/' // fallback for root items if any
      const entries = (await fsList(parentPath)).entries
      setChildren((prev) => ({ ...prev, [parentPath]: entries }))
    } catch (e: any) {
      alert(`Rename failed: ${e.message}`)
    }
  }

  useEffect(() => {
    ;(async () => {
      try {
        setError(null)
        const entries = (await fsList('/fs')).entries
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
        {entries.map((e) => (
          <FileTreeRow
            key={e.path}
            entry={e}
            indent={indent}
            isExpanded={!!expanded[e.path]}
            isSelected={props.selectedPath === e.path}
            onToggle={(p) => {
              void ensureLoaded(p)
              toggleDir(p)
            }}
            onSelect={props.onSelectFile}
            onOpen={props.onOpenFile ?? (() => {})}
            onContextMenu={(x, y, p) => setContextMenu({ x, y, path: p })}
          >
            {e.kind === 'dir' && expanded[e.path] ? renderDir(e.path, indent + 1) : null}
          </FileTreeRow>
        ))}
      </div>
    )
  }

  return (
    <div className="panel">
      {error ? <div className="error">{error}</div> : null}

      <div className="tree">
        {roots.map((r) => (
          <FileTreeRow
            key={r.path}
            entry={{ name: r.label, path: r.path, kind: 'dir', size: null }}
            indent={0}
            isExpanded={!!expanded[r.path]}
            isSelected={false}
            isRoot={true}
            onToggle={(p) => {
              void ensureLoaded(p)
              toggleDir(p)
            }}
            onSelect={() => {}}
            onOpen={() => {}}
            onContextMenu={(x, y, p) => setContextMenu({ x, y, path: p })}
          >
            {expanded[r.path] ? renderDir(r.path, 1) : null}
          </FileTreeRow>
        ))}
      </div>

      {contextMenu ? (
        <div
          style={{
            position: 'fixed',
            top: 0,
            left: 0,
            right: 0,
            bottom: 0,
            zIndex: 9999,
          }}
          onClick={() => setContextMenu(null)}
        >
          <div
            style={{
              position: 'absolute',
              top: contextMenu.y,
              left: contextMenu.x,
              background: '#252526',
              border: '1px solid #3c3c3c',
              boxShadow: '0 4px 6px rgba(0,0,0,0.3)',
              borderRadius: '4px',
              minWidth: '120px',
              padding: '4px 0',
            }}
          >
            <div
              style={{
                padding: '6px 12px',
                cursor: 'pointer',
                fontSize: '13px',
                color: '#d4d4d4',
              }}
              className="menuItem"
              onClick={(e) => {
                e.stopPropagation()
                handleRename(contextMenu.path)
              }}
            >
              Rename
            </div>
            <div
              style={{
                padding: '6px 12px',
                cursor: 'pointer',
                fontSize: '13px',
                color: '#d4d4d4',
              }}
              className="menuItem"
              onClick={(e) => {
                e.stopPropagation()
                navigator.clipboard.writeText(contextMenu.path)
                setContextMenu(null)
              }}
            >
              Copy Path
            </div>
            <div
              style={{
                padding: '6px 12px',
                cursor: 'pointer',
                fontSize: '13px',
                color: '#d4d4d4',
              }}
              className="menuItem"
              onClick={(e) => {
                e.stopPropagation()
                setContextMenu(null)
                setTreeCopyPath(contextMenu.path)
              }}
            >
              Copy Subtree
            </div>
          </div>
        </div>
      ) : null}
      
      {treeCopyPath ? (
        <TreeCopyModal
          path={treeCopyPath}
          onClose={() => setTreeCopyPath(null)}
        />
      ) : null}
    </div>
  )
}
