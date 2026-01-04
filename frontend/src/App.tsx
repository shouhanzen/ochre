import { useEffect, useMemo, useRef, useState } from 'react'
import { ChatPanel } from './components/ChatPanel'
import { ActivityBar } from './components/ActivityBar'
import { Editor } from './components/Editor'
import { EditorTabs } from './components/EditorTabs'
import { FileTree } from './components/FileTree'
import { SessionList } from './components/SessionList'
import { PendingPanel } from './components/PendingPanel'
import { SettingsModal } from './components/SettingsModal'
import { StatusBar } from './components/StatusBar'
import { MobileTabBar } from './components/MobileTabBar'
import { DebugModal } from './components/DebugModal'
import { createSession } from './sessionApi'

type MobileTab = 'browse' | 'editor' | 'chat' | 'pending'
type BrowseMode = 'files' | 'sessions'

function useIsMobile(breakpointPx = 900) {
  const [isMobile, setIsMobile] = useState<boolean>(() => {
    if (typeof window === 'undefined' || !window.matchMedia) return false
    return window.matchMedia(`(max-width: ${breakpointPx}px)`).matches
  })

  useEffect(() => {
    if (typeof window === 'undefined' || !window.matchMedia) return
    const mq = window.matchMedia(`(max-width: ${breakpointPx}px)`)
    const onChange = () => setIsMobile(mq.matches)
    onChange()
    if (mq.addEventListener) {
      mq.addEventListener('change', onChange)
      return () => mq.removeEventListener('change', onChange)
    }
    // Safari < 14
    // eslint-disable-next-line deprecation/deprecation
    mq.addListener(onChange)
    // eslint-disable-next-line deprecation/deprecation
    return () => mq.removeListener(onChange)
  }, [breakpointPx])

  return isMobile
}

function useViewportHeightVar(varName = '--ochre-vh') {
  useEffect(() => {
    if (typeof window === 'undefined' || typeof document === 'undefined') return

    const vv = window.visualViewport
    const set = () => {
      const h = vv?.height ?? window.innerHeight
      const top = vv?.offsetTop ?? 0
      document.documentElement.style.setProperty(varName, `${Math.round(h)}px`)
      document.documentElement.style.setProperty('--ochre-vv-top', `${Math.round(top)}px`)
    }

    set()
    vv?.addEventListener?.('resize', set)
    vv?.addEventListener?.('scroll', set)
    window.addEventListener('resize', set)
    window.addEventListener('orientationchange', set)

    return () => {
      vv?.removeEventListener?.('resize', set)
      vv?.removeEventListener?.('scroll', set)
      window.removeEventListener('resize', set)
      window.removeEventListener('orientationchange', set)
    }
  }, [varName])
}

function useLockBodyScroll(locked: boolean) {
  useEffect(() => {
    if (!locked) return
    if (typeof window === 'undefined' || typeof document === 'undefined') return

    const body = document.body
    const html = document.documentElement
    const scrollY = window.scrollY || 0

    const prev = {
      bodyOverflow: body.style.overflow,
      bodyPosition: body.style.position,
      bodyTop: body.style.top,
      bodyWidth: body.style.width,
      htmlOverflow: html.style.overflow,
    }

    html.style.overflow = 'hidden'
    body.style.overflow = 'hidden'
    body.style.position = 'fixed'
    body.style.top = `-${scrollY}px`
    body.style.width = '100%'

    return () => {
      html.style.overflow = prev.htmlOverflow
      body.style.overflow = prev.bodyOverflow
      body.style.position = prev.bodyPosition
      body.style.top = prev.bodyTop
      body.style.width = prev.bodyWidth
      window.scrollTo(0, scrollY)
    }
  }, [locked])
}

function useKeyboardOpen(enabled: boolean) {
  const [open, setOpen] = useState(false)

  useEffect(() => {
    if (!enabled) {
      setOpen(false)
      return
    }
    if (typeof window === 'undefined' || typeof document === 'undefined') return

    const vv = window.visualViewport
    const threshold = 140 // px, heuristic

    const compute = () => {
      const ae = document.activeElement as HTMLElement | null
      const tag = (ae?.tagName ?? '').toUpperCase()
      const isFormFocus = tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT'

      const vvHeight = vv?.height
      const isShrunk = typeof vvHeight === 'number' ? window.innerHeight - vvHeight > threshold : false

      setOpen(isFormFocus || isShrunk)
    }

    compute()
    document.addEventListener('focusin', compute)
    document.addEventListener('focusout', compute)
    vv?.addEventListener?.('resize', compute)
    vv?.addEventListener?.('scroll', compute)
    window.addEventListener('resize', compute)
    window.addEventListener('orientationchange', compute)

    return () => {
      document.removeEventListener('focusin', compute)
      document.removeEventListener('focusout', compute)
      vv?.removeEventListener?.('resize', compute)
      vv?.removeEventListener?.('scroll', compute)
      window.removeEventListener('resize', compute)
      window.removeEventListener('orientationchange', compute)
    }
  }, [enabled])

  return open
}

export default function App() {
  const PATH_STORAGE_KEY = 'ochre.selectedPath'
  const OPEN_FILES_KEY = 'ochre.openFiles'
  const SESSION_STORAGE_KEY = 'ochre.selectedSessionId'
  
  const [openFiles, setOpenFiles] = useState<string[]>(() => {
    try {
      const raw = localStorage.getItem(OPEN_FILES_KEY)
      if (raw) return JSON.parse(raw)
      return []
    } catch {
      return []
    }
  })

  const [selectedPath, setSelectedPath] = useState<string | undefined>(() => {
    try {
      return localStorage.getItem(PATH_STORAGE_KEY) || '/fs/todos/today.todo.md'
    } catch {
      return '/fs/todos/today.todo.md'
    }
  })
  const [sessionId, setSessionId] = useState<string | undefined>(() => {
    try {
      const v = localStorage.getItem(SESSION_STORAGE_KEY)
      return v && v.trim().length > 0 ? v : undefined
    } catch {
      return undefined
    }
  })
  const [sessionInitError, setSessionInitError] = useState<string | null>(null)
  const [settingsOpen, setSettingsOpen] = useState(false)
  const [debugOpen, setDebugOpen] = useState(false)
  const [activeRail, setActiveRail] = useState<'explorer' | 'sessions' | 'chat' | 'pending' | 'settings'>('explorer')
  const [ephemeralFile, setEphemeralFile] = useState<string | null>(null)
  const [dirtyFiles, setDirtyFiles] = useState<Set<string>>(new Set())
  const [fileViewModes, setFileViewModes] = useState<Record<string, 'source' | 'preview'>>({})
  const editorActions = useRef<{ save: () => void; saving: boolean } | null>(null)

  useViewportHeightVar()
  const isMobile = useIsMobile(900)
  useLockBodyScroll(isMobile)
  const keyboardOpen = useKeyboardOpen(isMobile)
  const [mobileTab, setMobileTab] = useState<MobileTab>('chat')
  const [browseMode, setBrowseMode] = useState<BrowseMode>('files')

  useEffect(() => {
    try {
      localStorage.setItem(OPEN_FILES_KEY, JSON.stringify(openFiles))
    } catch {
      // ignore
    }
  }, [openFiles])

  useEffect(() => {
    try {
      if (selectedPath) localStorage.setItem(PATH_STORAGE_KEY, selectedPath)
    } catch {
      // ignore
    }
  }, [selectedPath])

  useEffect(() => {
    try {
      if (sessionId) localStorage.setItem(SESSION_STORAGE_KEY, sessionId)
      else localStorage.removeItem(SESSION_STORAGE_KEY)
    } catch {
      // ignore
    }
  }, [sessionId])

  useEffect(() => {
    if (sessionId) return
    void newConversation()
  }, [sessionId])

  async function newConversation() {
    setSessionInitError(null)
    console.info('[Ochre] creating session…')
    try {
      const res = await createSession({ title: null })
      console.info('[Ochre] session created', { id: res.session.id })
      setSessionId(res.session.id)
    } catch (e: any) {
      const msg = e?.message ?? String(e)
      console.error('[Ochre] failed to create session', msg)
      setSessionInitError(msg)
    }
  }

  useEffect(() => {
    try {
      const url = new URL(window.location.href)
      const qp = url.searchParams.get('debug')
      if (qp === '1' || qp === 'true') setDebugOpen(true)
    } catch {
      // ignore
    }
  }, [])

  function handleSelectFile(path: string) {
    if (openFiles.includes(path)) {
      setSelectedPath(path)
    } else {
      setEphemeralFile(path)
      setSelectedPath(path)
    }
  }

  function handleOpenFile(path: string) {
    if (!openFiles.includes(path)) {
      setOpenFiles((prev) => [path, ...prev])
    }
    setEphemeralFile(null)
    setSelectedPath(path)
  }

  function handleCloseFile(path: string) {
    if (dirtyFiles.has(path)) {
      if (!confirm('Unsaved changes. Close anyway?')) return
      setDirtyFiles((prev) => {
        const next = new Set(prev)
        next.delete(path)
        return next
      })
    }

    const idx = openFiles.indexOf(path)
    if (idx !== -1) {
      const nextOpen = openFiles.filter((p) => p !== path)
      setOpenFiles(nextOpen)
      if (selectedPath === path) {
        if (nextOpen.length === 0) {
          setSelectedPath(ephemeralFile ?? undefined)
        } else {
          const nextIdx = Math.max(0, idx - 1)
          setSelectedPath(nextOpen[nextIdx] ?? nextOpen[0])
        }
      }
    } else if (path === ephemeralFile) {
      setEphemeralFile(null)
      if (selectedPath === path) {
        if (openFiles.length > 0) setSelectedPath(openFiles[openFiles.length - 1])
        else setSelectedPath(undefined)
      }
    }
  }

  function handleContentChange(path: string) {
    setDirtyFiles((prev) => {
      const next = new Set(prev)
      next.add(path)
      return next
    })
    if (ephemeralFile === path) {
      if (!openFiles.includes(path)) {
        setOpenFiles((prev) => [path, ...prev])
      }
      setEphemeralFile(null)
    }
  }

  function handleSaved(path: string) {
    setDirtyFiles((prev) => {
      const next = new Set(prev)
      next.delete(path)
      return next
    })
  }

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key === 's') {
        e.preventDefault()
        editorActions.current?.save()
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [])

  function handleToggleViewMode(path: string) {
    setFileViewModes((prev) => {
      const current = prev[path] ?? (path.endsWith('.todo.md') || path.endsWith('.task.md') ? 'preview' : 'source')
      return { ...prev, [path]: current === 'preview' ? 'source' : 'preview' }
    })
  }

  const currentViewMode = useMemo(() => {
    if (!selectedPath) return 'source'
    return (
      fileViewModes[selectedPath] ??
      (selectedPath.endsWith('.todo.md') || selectedPath.endsWith('.task.md') ? 'preview' : 'source')
    )
  }, [selectedPath, fileViewModes])

  const displayedFiles = useMemo(() => {
    if (ephemeralFile && !openFiles.includes(ephemeralFile)) {
      return [ephemeralFile, ...openFiles]
    }
    return openFiles
  }, [openFiles, ephemeralFile])

  if (isMobile) {
    return (
      <div className={keyboardOpen ? 'mobileShell keyboardOpen' : 'mobileShell'}>
        <div className="topBar mobileTopBar">
          <div className="brand">Ochre</div>
          <div className="muted mobileSubtitle">
            {mobileTab === 'browse'
              ? browseMode === 'files'
                ? 'Files'
                : 'Sessions'
              : mobileTab === 'editor'
                ? selectedPath ?? 'Editor'
                : mobileTab === 'chat'
                  ? 'Chat'
                  : 'Pending'}
          </div>
          <div className="row">
            <button className="button secondary" onClick={() => setSettingsOpen(true)}>
              Settings
            </button>
          </div>
        </div>

        <div className="mobileMain">
          {mobileTab === 'browse' ? (
            <div className="mobileBrowse">
              <div className="mobileBrowseToggle">
                <button
                  className={browseMode === 'files' ? 'button' : 'button secondary'}
                  onClick={() => setBrowseMode('files')}
                >
                  Files
                </button>
                <button
                  className={browseMode === 'sessions' ? 'button' : 'button secondary'}
                  onClick={() => setBrowseMode('sessions')}
                >
                  Sessions
                </button>
              </div>
              {browseMode === 'files' ? (
                <FileTree
                  selectedPath={selectedPath}
                  onSelectFile={(p) => {
                    handleSelectFile(p)
                    setMobileTab('editor')
                  }}
                  onOpenFile={(p) => {
                    handleOpenFile(p)
                    setMobileTab('editor')
                  }}
                />
              ) : (
                <SessionList
                  activeSessionId={sessionId}
                  onSelect={(id) => {
                    setSessionId(id)
                    setMobileTab('chat')
                  }}
                />
              )}
            </div>
          ) : null}

          {mobileTab === 'editor' ? (
            <div className="editorRegion">
              <EditorTabs
                files={displayedFiles}
                activeFile={selectedPath}
                ephemeralFile={ephemeralFile}
                dirtyFiles={dirtyFiles}
                viewMode={currentViewMode}
                onSelect={setSelectedPath}
                onClose={handleCloseFile}
                onToggleViewMode={handleToggleViewMode}
              />
              <Editor
                path={selectedPath}
                viewMode={currentViewMode}
                onNavigate={handleSelectFile}
                onChange={handleContentChange}
                onSaved={handleSaved}
                onMountActions={(a) => (editorActions.current = a)}
              />
            </div>
          ) : null}

          {mobileTab === 'chat' ? <ChatPanel sessionId={sessionId} variant="mobile" onNewConversation={newConversation} /> : null}
          {mobileTab === 'pending' ? <PendingPanel sessionId={sessionId} /> : null}
        </div>

        <SettingsModal
          open={settingsOpen}
          onClose={() => setSettingsOpen(false)}
          onOpenDebug={() => {
            setSettingsOpen(false)
            setDebugOpen(true)
          }}
        />
        <DebugModal open={debugOpen} onClose={() => setDebugOpen(false)} />
        {sessionInitError ? (
          <div className="error" style={{ position: 'fixed', left: 0, right: 0, bottom: 80, zIndex: 50 }}>
            Session init failed: {sessionInitError}
          </div>
        ) : null}
        {keyboardOpen ? null : <MobileTabBar active={mobileTab} onSelect={(t) => setMobileTab(t)} />}
      </div>
    )
  }

  return (
    <div className="vscodeShell">
      <div className="topBar">
        <div className="brand">Ochre</div>
        <div className="row">
          <button
            className="button secondary"
            onClick={() => setSettingsOpen(true)}
            title="Settings"
            style={{ padding: '4px 8px', border: 0, background: 'transparent' }}
          >
            <span style={{ fontSize: '16px', lineHeight: 1 }}>⚙</span>
          </button>
        </div>
      </div>

      <div className="vscodeMain">
        <ActivityBar
          active={activeRail}
          onSelect={(id) => {
            setActiveRail(id)
            if (id === 'settings') setSettingsOpen(true)
          }}
        />

        <div className="sideBar">
          {activeRail === 'sessions' ? (
            <SessionList activeSessionId={sessionId} onSelect={(id) => setSessionId(id)} />
          ) : activeRail === 'pending' ? (
            <PendingPanel sessionId={sessionId} />
          ) : (
            <FileTree selectedPath={selectedPath} onSelectFile={handleSelectFile} onOpenFile={handleOpenFile} />
          )}
        </div>

        <div className="editorRegion">
          <EditorTabs
            files={displayedFiles}
            activeFile={selectedPath}
            ephemeralFile={ephemeralFile}
            dirtyFiles={dirtyFiles}
            viewMode={currentViewMode}
            onSelect={setSelectedPath}
            onClose={handleCloseFile}
            onToggleViewMode={handleToggleViewMode}
          />
          <Editor
            path={selectedPath}
            viewMode={currentViewMode}
            onNavigate={handleSelectFile}
            onChange={handleContentChange}
            onSaved={handleSaved}
            onMountActions={(a) => (editorActions.current = a)}
          />
        </div>

        <div className="rightPanel">
          <ChatPanel sessionId={sessionId} onNewConversation={newConversation} />
        </div>
      </div>
      <SettingsModal open={settingsOpen} onClose={() => setSettingsOpen(false)} onOpenDebug={() => setDebugOpen(true)} />
      <DebugModal open={debugOpen} onClose={() => setDebugOpen(false)} />

      <StatusBar sessionId={sessionId} />
    </div>
  )
}
