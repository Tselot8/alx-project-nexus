import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { BrowserRouter } from 'react-router'
import { App } from './app/app'
import { AppErrorBoundary } from './app/error-boundary'
import { Providers } from './app/providers'
import { createServices } from './app/services'
import { capturePrivateShare } from './features/sharing/share-vault'
import { discardRecoveryCredentials } from './auth/navigation'
import './styles/tokens.css'
import './styles/global.css'

// Remove credentials from the URL before any session bootstrap/network work.
// Recovery is disabled. Do not retain credentials from an old reset link.
discardRecoveryCredentials(window)
const captured = capturePrivateShare(window)
const services = createServices()
const root = document.getElementById('root')
if (!root) throw new Error('Application root is missing.')
createRoot(root).render(<StrictMode><AppErrorBoundary><Providers services={services}>
  <BrowserRouter><App captured={captured} /></BrowserRouter>
</Providers></AppErrorBoundary></StrictMode>)
