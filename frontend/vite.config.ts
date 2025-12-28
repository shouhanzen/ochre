import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import { VitePWA } from 'vite-plugin-pwa'
import mkcert from 'vite-plugin-mkcert'

// https://vite.dev/config/
export default defineConfig({
  plugins: [
    react(),
    mkcert(),
    VitePWA({
      registerType: 'autoUpdate',
      includeAssets: ['ochre-icon.svg'],
      manifest: {
        name: 'Ochre',
        short_name: 'Ochre',
        description: 'Ochre: local chat agent + mounted filesystem + daily todos',
        start_url: '/',
        scope: '/',
        display: 'standalone',
        theme_color: '#0f172a',
        background_color: '#0f172a',
        icons: [
          {
            src: '/ochre-icon.svg',
            sizes: 'any',
            type: 'image/svg+xml',
            purpose: 'any',
          },
        ],
      },
      devOptions: {
        enabled: true,
      },
      workbox: {
        // Never let the SW hijack API or websocket endpoints.
        navigateFallbackDenylist: [/^\/api\//, /^\/ws\//],
        runtimeCaching: [
          {
            urlPattern: /^\/api\//,
            handler: 'NetworkOnly',
            options: { cacheName: 'api-network-only' },
          },
          {
            urlPattern: /^\/ws\//,
            handler: 'NetworkOnly',
            options: { cacheName: 'ws-network-only' },
          },
        ],
      },
    }),
  ],
  server: {
    // Required for PWA installability over LAN IPs (localhost is the only HTTP exception).
    https: {},
    proxy: {
      '/api': 'http://localhost:8000',
      '/ws': {
        target: 'ws://localhost:8000',
        ws: true,
      },
    },
  },
})
