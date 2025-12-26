import { useEffect, useMemo, useState } from 'react'
import { clearDebugEntries, subscribeDebugEntries, type DebugEntry } from '../debugLog'

function format(entries: DebugEntry[]): string {
  return entries
    .map((e) => {
      const head = `[${e.ts}] ${e.level.toUpperCase()}: ${e.message}`
      if (e.detail && e.detail.trim()) return `${head}\n${e.detail}\n`
      return `${head}\n`
    })
    .join('\n')
    .trimEnd()
}

export function DebugModal(props: { open: boolean; onClose: () => void }) {
  const [entries, setEntries] = useState<DebugEntry[]>([])
  const [copied, setCopied] = useState(false)

  useEffect(() => {
    if (!props.open) return
    console.info('[Ochre Debug] Debug console opened')
    return subscribeDebugEntries(setEntries)
  }, [props.open])

  const text = useMemo(() => format(entries), [entries])

  async function copy() {
    setCopied(false)
    try {
      await navigator.clipboard.writeText(text || '(no logs)')
      setCopied(true)
      setTimeout(() => setCopied(false), 1200)
    } catch {
      // ignore; user can manually select/copy
      setCopied(false)
    }
  }

  function testLogs() {
    console.log('[Ochre Debug] test log', { hello: 'world', n: 1 })
    console.info('[Ochre Debug] test info')
    console.warn('[Ochre Debug] test warn')
    console.error('[Ochre Debug] test error')
  }

  if (!props.open) return null

  return (
    <div className="modalBackdrop" onMouseDown={props.onClose}>
      <div className="modal" onMouseDown={(e) => e.stopPropagation()}>
        <div className="panelHeader">
          <div className="panelTitle">Debug</div>
          <div className="muted">{entries.length} events</div>
          <div className="row">
            <button className="button secondary" onClick={testLogs}>
              Test logs
            </button>
            <button className="button secondary" onClick={() => clearDebugEntries()}>
              Clear
            </button>
            <button className="button secondary" onClick={() => void copy()}>
              {copied ? 'Copied' : 'Copy'}
            </button>
            <button className="button" onClick={props.onClose}>
              Close
            </button>
          </div>
        </div>

        <div style={{ padding: 12 }}>
          <textarea
            className="textarea"
            readOnly
            value={text || '(no logs yet)'}
            style={{ height: '60vh' }}
            spellCheck={false}
          />
          <div className="muted" style={{ marginTop: 8 }}>
            Tip: if Copy doesn’t work (non-HTTPS), press-hold in the box → Select All → Copy.
          </div>
        </div>
      </div>
    </div>
  )
}

