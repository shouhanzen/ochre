import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import './index.css'
import App from './App.tsx'
import { installDebugCapture } from './debugLog'

installDebugCapture()

function logRuntimeSignals() {
  const nav: any = navigator as any
  const conn = nav?.connection
  const connInfo =
    conn && typeof conn === 'object'
      ? {
          effectiveType: typeof conn.effectiveType === 'string' ? conn.effectiveType : null,
          rtt: typeof conn.rtt === 'number' ? conn.rtt : null,
          downlink: typeof conn.downlink === 'number' ? conn.downlink : null,
          saveData: typeof conn.saveData === 'boolean' ? conn.saveData : null,
        }
      : null

  console.info('[Ochre] runtime', {
    ua: typeof navigator !== 'undefined' ? navigator.userAgent : null,
    online: typeof navigator !== 'undefined' && 'onLine' in navigator ? !!navigator.onLine : null,
    visibility: typeof document !== 'undefined' ? document.visibilityState : null,
    standalone: (window.matchMedia && window.matchMedia('(display-mode: standalone)').matches) || (nav?.standalone ?? false),
    connection: connInfo,
  })

  window.addEventListener('online', () => console.info('[Ochre] online', { online: true, connection: connInfo }))
  window.addEventListener('offline', () => console.warn('[Ochre] offline', { online: false, connection: connInfo }))
  document.addEventListener('visibilitychange', () =>
    console.info('[Ochre] visibilitychange', { visibility: document.visibilityState, online: 'onLine' in navigator ? !!navigator.onLine : null }),
  )

  if ('serviceWorker' in navigator) {
    // Helpful for PWA-only issues: confirms which SW (if any) is controlling this page.
    navigator.serviceWorker.getRegistration().then((reg) => {
      console.info('[Ochre] serviceWorker', {
        controller: navigator.serviceWorker.controller?.scriptURL ?? null,
        scope: reg?.scope ?? null,
        active: reg?.active?.scriptURL ?? null,
        waiting: reg?.waiting?.scriptURL ?? null,
        installing: reg?.installing?.scriptURL ?? null,
      })
    })
    navigator.serviceWorker.addEventListener('controllerchange', () => {
      console.info('[Ochre] serviceWorker controllerchange', { controller: navigator.serviceWorker.controller?.scriptURL ?? null })
    })
  }
}

logRuntimeSignals()

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <App />
  </StrictMode>,
)
