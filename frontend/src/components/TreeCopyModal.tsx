import { useEffect, useRef, useState } from 'react'
import { fsTree } from '../api'

export function TreeCopyModal(props: { path: string; onClose: () => void }) {
  const [content, setContent] = useState('')
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [copied, setCopied] = useState(false)
  const textareaRef = useRef<HTMLTextAreaElement>(null)

  useEffect(() => {
    setLoading(true)
    setError(null)
    setContent('')
    ;(async () => {
      try {
        const res = await fsTree(props.path)
        setContent(res.tree)
        
        // Auto-select text once loaded
        setTimeout(() => {
            textareaRef.current?.select()
        }, 50)

      } catch (e: any) {
        setError(e?.message ?? String(e))
      } finally {
        setLoading(false)
      }
    })()
  }, [props.path])

  async function handleCopy() {
    // Try modern clipboard first
    try {
      await navigator.clipboard.writeText(content)
      setCopied(true)
      setTimeout(() => setCopied(false), 2000)
    } catch {
      // Fallback to execCommand which works well in modals with active user interaction
      try {
        textareaRef.current?.select()
        document.execCommand('copy')
        setCopied(true)
        setTimeout(() => setCopied(false), 2000)
      } catch (e) {
        alert('Could not copy. Please manually select the text and copy.')
      }
    }
  }

  return (
    <div className="modalBackdrop" onMouseDown={props.onClose}>
      <div 
        className="modal" 
        style={{ height: '80vh', display: 'flex', flexDirection: 'column' }} 
        onMouseDown={(e) => e.stopPropagation()}
      >
        <div className="panelHeader">
          <div className="panelTitle">Copy Tree: {props.path}</div>
          <div className="row">
            <button className="button secondary" onClick={props.onClose}>
              Close
            </button>
            <button 
              className="button" 
              onClick={handleCopy} 
              disabled={loading || !!error}
            >
              {copied ? 'Copied!' : 'Copy'}
            </button>
          </div>
        </div>
        
        <div style={{ flex: 1, overflow: 'hidden', padding: 12, display: 'flex', flexDirection: 'column' }}>
          {error ? (
            <div className="error">{error}</div>
          ) : loading ? (
            <div className="muted" style={{ padding: 20, textAlign: 'center' }}>Generating tree...</div>
          ) : (
            <textarea
              ref={textareaRef}
              className="textarea"
              style={{ flex: 1, fontFamily: 'monospace', whiteSpace: 'pre' }}
              value={content}
              readOnly
              onClick={(e) => (e.target as HTMLTextAreaElement).select()}
            />
          )}
        </div>
      </div>
    </div>
  )
}
