import { useState, useRef, useEffect } from 'react'

export function ChatComposer(props: {
  sessionId?: string
  isMobile?: boolean
  canSend: boolean
  streaming: boolean
  onSend: (text: string) => void
}) {
  const [draft, setDraft] = useState('')
  const textareaRef = useRef<HTMLTextAreaElement>(null)

  function handleSend() {
    if (!draft.trim()) return
    props.onSend(draft)
    setDraft('')
    if (textareaRef.current) {
      textareaRef.current.style.height = '34px'
      // Keep focus on desktop, maybe dismiss on mobile? usually keeping focus is better for chat.
      if (!props.isMobile) {
        textareaRef.current.focus()
      }
    }
  }

  return (
    <div className={props.isMobile ? 'chatComposer compact' : 'chatComposer'}>
      <textarea
        ref={textareaRef}
        className="textarea"
        value={draft}
        onChange={(e) => {
           setDraft(e.target.value)
           // Auto-expand height
           e.target.style.height = 'auto'
           e.target.style.height = `${Math.min(e.target.scrollHeight, 120)}px`
        }}
        placeholder={props.sessionId ? 'Send a message…' : 'Waiting for session…'}
        rows={1}
        inputMode="text"
        enterKeyHint="send"
        autoComplete={props.isMobile ? 'off' : undefined}
        autoCorrect={props.isMobile ? 'off' : undefined}
        autoCapitalize={props.isMobile ? 'none' : undefined}
        spellCheck={props.isMobile ? false : undefined}
        onKeyDown={(e) => {
          if (e.key === 'Enter' && !e.shiftKey) {
            e.preventDefault()
            handleSend()
          }
        }}
        disabled={!props.sessionId}
        style={{ height: '34px' }}
      />
      <button
        className="button"
        disabled={!props.sessionId || !props.canSend || !draft.trim()}
        onClick={handleSend}
        style={{
           borderRadius: '50%',
           width: '32px',
           height: '32px',
           padding: 0,
           display: 'grid',
           placeItems: 'center',
           flexShrink: 0
        }}
      >
        {props.streaming ? (
           <span style={{ fontSize: '12px' }}>■</span>
        ) : (
           <svg width="16" height="16" viewBox="0 0 16 16" fill="currentColor">
             <path d="M1.5 8.5L14.5 2L8 14.5L6.5 9.5L1.5 8.5Z" />
           </svg>
        )}
      </button>
    </div>
  )
}
