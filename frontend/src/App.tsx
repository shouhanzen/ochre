import { useEffect, useState } from 'react'
import { ChatPanel } from './components/ChatPanel'
import { ActivityBar } from './components/ActivityBar'
import { Editor } from './components/Editor'
import { FileTree } from './components/FileTree'
import { SessionList } from './components/SessionList'
import { TodoPanel } from './components/TodoPanel'
import { PendingPanel } from './components/PendingPanel'
import { SettingsModal } from './components/SettingsModal'
import { StatusBar } from './components/StatusBar'
import { MobileTabBar } from './components/MobileTabBar'
import { DebugModal } from './components/DebugModal'
import { createSession } from './sessionApi'

type MobileTab = 'browse' | 'editor' | 'chat' | 'today' | 'pending'
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
      const w = vv?.width ?? window.innerWidth
      const top = vv?.offsetTop ?? 0
      const left = vv?.offsetLeft ?? 0
      document.documentElement.style.setProperty(varName, `${Math.round(h)}px`)
      document.documentElement.style.setProperty('--ochre-vw', `${Math.round(w)}px`)
      document.documentElement.style.setProperty('--ochre-vv-top', `${Math.round(top)}px`)
      document.documentElement.style.setProperty('--ochre-vv-left', `${Math.round(left)}px`)
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
  const STORAGE_KEY = 'ochre.selectedPath'
  const [selectedPath, setSelectedPath] = useState<string | undefined>(() => {
    try {
      return localStorage.getItem(STORAGE_KEY) || '/fs/todos/today.md'
    } catch {
      return '/fs/todos/today.md'
    }
  })
  const [todoRefreshKey, setTodoRefreshKey] = useState(0)
  const [sessionId, setSessionId] = useState<string | undefined>(undefined)
  const [sessionInitError, setSessionInitError] = useState<string | null>(null)
  const [settingsOpen, setSettingsOpen] = useState(false)
  const [debugOpen, setDebugOpen] = useState(false)
  const [activeRail, setActiveRail] = useState<'explorer' | 'sessions' | 'chat' | 'kanban' | 'settings'>('explorer')

  useViewportHeightVar()
  const isMobile = useIsMobile(900)
  useLockBodyScroll(isMobile)
  const keyboardOpen = useKeyboardOpen(isMobile)
  const [mobileTab, setMobileTab] = useState<MobileTab>('chat')
  const [browseMode, setBrowseMode] = useState<BrowseMode>('files')

  useEffect(() => {
    try {
      if (selectedPath) localStorage.setItem(STORAGE_KEY, selectedPath)
    } catch {
      // ignore
    }
  }, [selectedPath])

  useEffect(() => {
    if (sessionId) return
    ;(async () => {
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
    })()
  }, [sessionId])

  useEffect(() => {
    try {
      const url = new URL(window.location.href)
      const qp = url.searchParams.get('debug')
      if (qp === '1' || qp === 'true') setDebugOpen(true)
    } catch {
      // ignore
    }
  }, [])

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
                  : mobileTab === 'today'
                    ? 'Today'
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
                    setSelectedPath(p)
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
            <Editor
              path={selectedPath}
              onNavigate={(p) => setSelectedPath(p)}
              onSaved={(p) => {
                if (p.startsWith('/fs/todos/')) setTodoRefreshKey((k) => k + 1)
              }}
            />
          ) : null}

          {mobileTab === 'chat' ? <ChatPanel sessionId={sessionId} /> : null}
          {mobileTab === 'today' ? <TodoPanel refreshKey={todoRefreshKey} /> : null}
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
        <div className="muted">VS Code-style</div>
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
          ) : (
            <FileTree selectedPath={selectedPath} onSelectFile={(p) => setSelectedPath(p)} />
          )}
        </div>

        <div className="editorRegion">
          <Editor
            path={selectedPath}
            onNavigate={(p) => setSelectedPath(p)}
            onSaved={(p) => {
              if (p.startsWith('/fs/todos/')) setTodoRefreshKey((k) => k + 1)
            }}
          />
        </div>

        <div className="rightPanel">
          <ChatPanel sessionId={sessionId} />
          <PendingPanel sessionId={sessionId} />
          <TodoPanel refreshKey={todoRefreshKey} />
        </div>
      </div>
      <SettingsModal open={settingsOpen} onClose={() => setSettingsOpen(false)} onOpenDebug={() => setDebugOpen(true)} />
      <DebugModal open={debugOpen} onClose={() => setDebugOpen(false)} />

      <StatusBar sessionId={sessionId} />
    </div>
  )
}
