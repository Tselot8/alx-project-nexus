import { Route, Routes, useLocation } from 'react-router'
import { useEffect } from 'react'
import { Layout } from './layout'
import { ProtectedRoute } from './providers'
import type { CapturedShare } from '../features/sharing/share-vault'
import { AuthPage } from '../pages/auth-page'
import { FoundationPage, NotFound } from '../pages/foundation'
import { Home } from '../pages/home'
import { Explore } from '../pages/explore'
import { PollDetailPage } from '../pages/poll-detail'
import { ShareGate } from '../features/sharing/share-gate'

export function App({ captured = null }: { captured?: CapturedShare }) {
  const location = useLocation()
  useEffect(() => {
    const path = location.pathname
    const title = path === '/' ? 'Home' : path === '/polls' ? 'Explore polls'
      : path === '/login' ? 'Sign in' : path === '/register' ? 'Create account'
      : path === '/my-polls' ? 'My polls' : path === '/polls/new' ? 'Create poll'
      : path === '/profile' ? 'My profile' : path.startsWith('/polls/') ? 'Poll' : 'Page not found'
    document.title = title + ' · Project Nexus'
  }, [location.pathname])
  return <Routes><Route element={<Layout />}><Route element={<ShareGate captured={captured} />}>
    <Route index element={<Home />} /><Route path="polls" element={<Explore />} />
    <Route path="polls/:id" element={<PollDetailPage />} />
    <Route path="login" element={<AuthPage />} /><Route path="register" element={<AuthPage register />} />
    <Route element={<ProtectedRoute />}>
      <Route path="my-polls" element={<FoundationPage kind="mine" />} />
      <Route path="polls/new" element={<FoundationPage kind="create" />} />
      <Route path="profile" element={<FoundationPage kind="profile" />} />
    </Route>
    <Route path="*" element={<NotFound />} />
  </Route></Route></Routes>
}
