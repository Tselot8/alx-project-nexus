import { Route, Routes, useLocation } from 'react-router'
import { useEffect } from 'react'
import { Layout } from './layout'
import { ProtectedRoute } from './providers'
import type { CapturedShare } from '../features/sharing/share-vault'
import { AuthPage } from '../pages/auth-page'
import { NotFound } from '../pages/foundation'
import { Home } from '../pages/home'
import { Explore } from '../pages/explore'
import { PollDetailPage } from '../pages/poll-detail'
import { ShareGate } from '../features/sharing/share-gate'
import { CreatePoll } from '../pages/create-poll'
import { MyPolls } from '../pages/my-polls'
import { ManagePoll } from '../pages/manage-poll'
import { Profile, RecoveryUnavailable } from '../pages/profile'

export function App({ captured = null }: { captured?: CapturedShare }) {
  const location = useLocation()
  useEffect(() => {
    const path = location.pathname
    const title = path === '/' ? 'Home' : path === '/polls' ? 'Explore polls'
      : path === '/login' ? 'Sign in' : path === '/register' ? 'Create account'
      : path === '/my-polls' ? 'My polls' : path === '/polls/new' ? 'Create poll'
      : path === '/profile' ? 'My profile' : path === '/forgot-password' || path === '/reset-password' ? 'Account recovery'
      : path.endsWith('/manage') && path.startsWith('/polls/') ? 'Manage poll' : path.startsWith('/polls/') ? 'Poll' : 'Page not found'
    document.title = title + ' · Project Nexus'
  }, [location.pathname])
  return <Routes><Route element={<Layout />}><Route element={<ShareGate captured={captured} />}>
    <Route index element={<Home />} /><Route path="polls" element={<Explore />} />
    <Route path="polls/:id" element={<PollDetailPage />} />
    <Route path="forgot-password" element={<RecoveryUnavailable />} /><Route path="reset-password" element={<RecoveryUnavailable />} />
    <Route path="login" element={<AuthPage />} /><Route path="register" element={<AuthPage register />} />
    <Route element={<ProtectedRoute />}>
      <Route path="my-polls" element={<MyPolls />} />
      <Route path="polls/new" element={<CreatePoll />} />
      <Route path="profile" element={<Profile />} />
      <Route path="polls/:id/manage" element={<ManagePoll />} />
    </Route>
    <Route path="*" element={<NotFound />} />
  </Route></Route></Routes>
}
