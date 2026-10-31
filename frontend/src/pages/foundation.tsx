import { Link, useParams } from 'react-router'
import { useSession } from '../app/providers'
import { Card, EmptyState, Initials } from '../ui/components'

export function FoundationPage({ kind }: { kind: 'explore' | 'detail' | 'mine' | 'create' | 'profile' }) {
  const params = useParams()
  const session = useSession()
  const copy = {
    explore: { eyebrow: 'Explore polls', title: 'A good question is a great beginning.', empty: 'Discovery is taking shape', text: 'Search, categories, and public polls will arrive in the next release. No polls are displayed in this preview.' },
    detail: { eyebrow: 'Poll workspace', title: 'A space for every perspective.', empty: 'The poll experience is on its way', text: 'Poll details, voting, saved selections, and results will be available in the next release.' },
    mine: { eyebrow: 'Your workspace', title: 'Good questions start with you.', empty: 'Your polls will feel at home here', text: 'Your personal poll list, sharing tools, and lifecycle controls are being prepared. No poll data is displayed in this preview.' },
    create: { eyebrow: 'Create a poll', title: 'What would you like to ask?', empty: 'Your poll editor is being prepared', text: 'A single, focused editor for your question, options, privacy, and publishing settings is coming next. This preview cannot create or save a poll.' },
    profile: { eyebrow: 'Private profile', title: 'A little more you.', empty: 'Make this space your own', text: 'Profile editing and account settings are coming in the next release. Your email remains read-only.' },
  }[kind]
  if (kind === 'detail' && !/^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$/i.test(params.id || '')) return <NotFound />
  return <section className="page-section"><div className="page-heading"><p className="eyebrow">{copy.eyebrow}</p>
    <h1>{copy.title}</h1><p className="page-lead">Simple, focused, and built around people.</p></div>
    {kind === 'profile' && session.status === 'authenticated' && <Card className="profile-card">
      <Initials name={session.user.username} /><div><h2>{session.user.username}</h2><p>{session.user.email}</p>
        {session.user.profile.bio && <p>{session.user.profile.bio}</p>}
        {session.user.profile.location && <p>{session.user.profile.location}</p>}</div><span className="pill">Only visible to you</span>
    </Card>}
    <Card><div className="card-topline"><span className="pill">In progress</span><span className="muted">Preview</span></div>
      <EmptyState title={copy.empty}>{copy.text}</EmptyState>
      <div className="empty-actions"><Link className="button button--secondary" to="/">Back to home</Link>
        {kind !== 'explore' && <Link className="button button--quiet" to="/polls">Explore Nexus</Link>}</div>
    </Card>
  </section>
}
export function NotFound() {
  return <section className="page-section"><Card><p className="eyebrow">404 · Page not found</p>
    <h1>This page isn’t here.</h1><p>The address may have changed. Let’s find your way back.</p>
    <Link className="button button--primary" to="/">Return home</Link></Card></section>
}
