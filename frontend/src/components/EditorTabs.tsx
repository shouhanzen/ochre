import React, { useRef, useEffect } from 'react'

export function EditorTabs(props: {
  files: string[]
  activeFile?: string
  ephemeralFile?: string | null
  dirtyFiles?: Set<string>
  viewMode?: 'source' | 'preview'
  onSelect: (path: string) => void
  onClose: (path: string) => void
  onSave?: () => void
  onToggleViewMode?: (path: string) => void
  saving?: boolean
}) {
  const scrollRef = useRef<HTMLDivElement>(null)

  // Auto-scroll to active tab
  useEffect(() => {
    if (!props.activeFile || !scrollRef.current) return
    const activeEl = scrollRef.current.querySelector(`[data-path="${props.activeFile}"]`) as HTMLElement
    if (activeEl) {
      activeEl.scrollIntoView({ behavior: 'smooth', block: 'nearest', inline: 'nearest' })
    }
  }, [props.activeFile])

  if (props.files.length === 0) return null

  return (
    <div className="editorTabsContainer">
      <div className="editorTabs" ref={scrollRef}>
        {props.files.map((path) => {
          const name = path.split('/').pop() || path
          const isActive = path === props.activeFile
          const isEphemeral = path === props.ephemeralFile
          const isDirty = props.dirtyFiles?.has(path)
          return (
            <div
              key={path}
              className={`editorTab ${isActive ? 'active' : ''} ${isEphemeral ? 'ephemeral' : ''}`}
              data-path={path}
              onClick={() => props.onSelect(path)}
              title={path}
            >
              <span className="editorTabLabel">{name}</span>
              <button
                className={`editorTabClose ${isDirty ? 'dirty' : ''}`}
                onClick={(e) => {
                  e.stopPropagation()
                  props.onClose(path)
                }}
                title={isDirty ? 'Unsaved changes' : 'Close'}
              >
                {isDirty ? '●' : '×'}
              </button>
            </div>
          )
        })}
      </div>
      {props.activeFile && (props.onSave || props.onToggleViewMode) ? (
        <div className="editorSave">
          {(props.activeFile.endsWith('.md') || props.activeFile.endsWith('.todo.md')) && props.onToggleViewMode ? (
            <button
              className="button secondary"
              onClick={() => props.onToggleViewMode?.(props.activeFile!)}
              title={props.viewMode === 'preview' ? 'Switch to Source' : 'Switch to Preview'}
              style={{ marginRight: '8px' }}
            >
              {props.viewMode === 'preview' ? 'Source' : 'Preview'}
            </button>
          ) : null}
          {props.onSave ? (
            <button
              className="button"
              onClick={props.onSave}
              disabled={props.saving}
            >
              {props.saving ? 'Saving…' : 'Save'}
            </button>
          ) : null}
        </div>
      ) : null}
    </div>
  )
}

