import react from '@vitejs/plugin-react'
import { loadEnv } from 'vite'
import { defineConfig } from 'vitest/config'

export default defineConfig(({ mode }) => {
  // This variable stays on the dev server; never expose backend credentials.
  const env = loadEnv(mode, process.cwd(), 'NEXUS_')
  const target = new URL(env.NEXUS_PROXY_TARGET || 'http://127.0.0.1:8000')
  if (!['localhost', '127.0.0.1', '[::1]'].includes(target.hostname)
      || !['http:', 'https:'].includes(target.protocol)
      || target.username || target.password || target.search || target.hash
      || target.pathname !== '/') {
    throw new Error('The development proxy must target a loopback Django server.')
  }
  return {
    plugins: [react()],
    server: {
      host: 'localhost', port: 5173, strictPort: true,
      proxy: { '/api/': { target: target.origin, changeOrigin: false } },
    },
    preview: { host: 'localhost', port: 4173, strictPort: true },
    test: {
      environment: 'jsdom', setupFiles: ['./src/test/setup.ts'],
      restoreMocks: true, clearMocks: true, unstubGlobals: true,
      maxWorkers: 2,
    },
  }
})
