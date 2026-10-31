import { Route, Routes, useLocation } from 'react-router'
import { useEffect } from 'react'
import { Layout } from './layout'
import { PrivateShareNotice, ProtectedRoute } from './providers'
import type { CapturedShare } from '../features/sharing/share-vault'
import { AuthPage } from '../pages/auth-page'
import { FoundationPage, NotFound } from '../pages/foundation'
import { Home } from '../pages/home'

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
  return <Routes><Route element={<Layout notice={<PrivateShareNotice captured={captured} />} />}>
    <Route index element={<Home />} /><Route path="polls" element={<FoundationPage kind="explore" />} />
    <Route path="polls/:id" element={<FoundationPage kind="detail" />} />
    <Route path="login" element={<AuthPage />} /><Route path="register" element={<AuthPage register />} />
    <Route element={<ProtectedRoute />}>
      <Route path="my-polls" element={<FoundationPage kind="mine" />} />
      <Route path="polls/new" element={<FoundationPage kind="create" />} />
      <Route path="profile" element={<FoundationPage kind="profile" />} />
    </Route>
    <Route path="*" element={<NotFound />} />
  </Route></Routes>
}
