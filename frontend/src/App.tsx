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
import { createSession } from './sessionApi'

export default function App() {
  const [selectedPath, setSelectedPath] = useState<string | undefined>('/fs/todos/today.md')
  const [todoRefreshKey, setTodoRefreshKey] = useState(0)
  const [sessionId, setSessionId] = useState<string | undefined>(undefined)
  const [settingsOpen, setSettingsOpen] = useState(false)
  const [activeRail, setActiveRail] = useState<'explorer' | 'sessions' | 'chat' | 'kanban' | 'settings'>('explorer')

  useEffect(() => {
    if (sessionId) return
    ;(async () => {
      const res = await createSession({ title: null })
      setSessionId(res.session.id)
    })()
  }, [sessionId])

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
      <SettingsModal open={settingsOpen} onClose={() => setSettingsOpen(false)} />

      <StatusBar sessionId={sessionId} />
    </div>
  )
}
