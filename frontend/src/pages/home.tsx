import { Link } from 'react-router'
import { useServices, useSession } from '../app/providers'
import { useCategories, usePublicPolls } from '../features/polls/api'
import { PollCard, useNow } from '../features/polls/presentation'
import { Button, Card, EmptyState, Feedback, Loading } from '../ui/components'

export function Home() {
  const { api } = useServices()
  const session = useSession()
  const polls = usePublicPolls(api, { sort: 'newest', page: 1 })
  const categories = useCategories(api, 1)
  const now = useNow()
  return <>
    <section className="hero">
      <div><p className="eyebrow"><span className="status-dot" />A little curiosity goes a long way</p>
        <h1>Different voices.<br /><span className="text-blue">Clearer decisions.</span></h1>
        <p className="hero-description">A place for good questions and thoughtful answers. Discover public polls, bring people together, and make space for every perspective.</p>
        <div className="action-row"><Link to="/polls" className="button button--primary">Browse polls <span aria-hidden="true">↗</span></Link>
          <Link to="/polls/new" className="button button--secondary">Create a poll</Link></div>
        <p className="supporting-copy">{session.status === 'authenticated' ? 'Welcome back. Find your next good question.' : 'Browse freely. Sign in to take part when voting is available.'}</p>
      </div>
      <Card className="signal-card">
        <span className="pill">A clearer signal</span>
        <div className="signal-graphic" aria-hidden="true"><div /><div /><div /><div /></div>
        <h2>Better questions.<br />Shared understanding.</h2>
        <p>From a quick check-in to the next big idea, start with the people who matter.</p>
        <span className="signal-caption"><span className="status-dot" />Ask · Share · Understand</span>
      </Card>
    </section>
    <section className="intro-section" aria-labelledby="recent-polls">
      <div className="results-topline"><div><p className="eyebrow">Fresh perspectives</p><h2 id="recent-polls">Recent public polls</h2></div>
        <Link to="/polls">Explore all polls</Link></div>
      {polls.isPending ? <Loading label="Loading recent polls…" /> : polls.isError ? <Card>
        <Feedback tone="error">We could not load recent polls.</Feedback>
        <Button variant="secondary" onClick={() => { void polls.refetch() }}>Retry recent polls</Button>
      </Card> : polls.data.results.length ? <div className="poll-grid">{polls.data.results.slice(0, 3).map(poll =>
        <PollCard key={poll.id} poll={poll} categories={categories.data?.results || []} now={now} />)}</div>
        : <Card><EmptyState title="The next question could be yours.">No public polls are available yet. Check back soon or start a poll of your own.</EmptyState></Card>}
    </section>
    <section className="intro-section" aria-labelledby="possibilities"><div className="section-heading">
      <p className="eyebrow">Thoughtful by design</p><h2 id="possibilities">One question. More possibilities.</h2></div>
      <div className="feature-grid">{[
        ['01', 'Find your curiosity', 'Explore public questions by topic and discover perspectives beyond your own.'],
        ['02', 'Understand the question', 'Read the options, closing date, and results policy before participating.'],
        ['03', 'Bring people together', 'Poll creation, participation, and results tools are coming in upcoming releases.'],
      ].map(([number, title, text]) => <Card key={number}><span className="feature-number">{number}</span>
        <h3>{title}</h3><p>{text}</p></Card>)}</div>
    </section>
  </>
}
