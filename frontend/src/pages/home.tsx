import { Link } from 'react-router'
import { useServices, useSession } from '../app/providers'
import { useCategories, usePublicPolls } from '../features/polls/api'
import { PollCard, useNow } from '../features/polls/presentation'
import { Button, Card, EmptyState, Feedback, Loading } from '../ui/components'
import { ArrowMark, BallotArtwork, PaperMark } from '../ui/illustrations'

export function Home() {
  const { api } = useServices()
  const session = useSession()
  const polls = usePublicPolls(api, { sort: 'newest', page: 1 })
  const categories = useCategories(api, 1)
  const now = useNow()
  return <>
    <section className="hero">
      <div className="hero-copy"><p className="eyebrow">A little curiosity. A lot of possibility.</p>
        <h1>Put it to<br /><span className="vote-word">a vote.</span></h1>
        <p className="hero-description">Big ideas, everyday dilemmas, and everything in between. Ask a question, hear a few different takes, and see where we stand.</p>
        <div className="action-row"><Link to="/polls" className="button button--primary">Browse polls <ArrowMark /></Link>
          <Link to="/polls/new" className="button button--secondary">Create a poll</Link></div>
        <p className="supporting-copy">{session.status === 'authenticated' ? 'Welcome back. There is always another good question.' : 'No account needed to look around. Sign in when you want to weigh in.'}</p>
      </div>
      <figure className="hero-visual"><BallotArtwork />
        <figcaption className="art-caption">Different perspectives. Shared possibilities.</figcaption>
      </figure>
    </section>
    <div className="home-rule"><span>Everyday questions, open conversations</span><span>Your choice, yours to update while voting is open</span></div>
    <section className="intro-section home-polls" aria-labelledby="recent-polls">
      <div className="results-topline"><div><p className="eyebrow">On the table</p><h2 id="recent-polls">Recent public polls</h2></div>
        <Link to="/polls">Explore all polls <ArrowMark /></Link></div>
      {polls.isPending ? <Loading label="Loading recent polls…" /> : polls.isError ? <Card>
        <Feedback tone="error">We could not load recent polls.</Feedback>
        <Button variant="secondary" onClick={() => { void polls.refetch() }}>Retry recent polls</Button>
      </Card> : polls.data.results.length ? <div className="poll-grid">{polls.data.results.slice(0, 3).map(poll =>
        <PollCard key={poll.id} poll={poll} categories={categories.data?.results || []} now={now} />)}</div>
        : <Card><EmptyState title="The next question could be yours.">No public polls are available yet. Check back soon or start a poll of your own.</EmptyState></Card>}
    </section>
    <section className="how-it-works" aria-labelledby="possibilities">
      <div className="how-intro"><PaperMark /><h2 id="possibilities">A good question makes room for everyone.</h2>
        <p>No long setup. Just something worth asking, and people with a point of view.</p>
        <Link className="button button--secondary" to="/polls/new">Start with your question <ArrowMark diagonal /></Link></div>
      <ol>{[
        ['01', 'Ask something real.', 'Pick your question, add a few options, and decide how you want to hear from people.'],
        ['02', 'Make your choice.', 'Choose an answer or a few. You can update your complete ballot while the poll is open.'],
        ['03', 'See the bigger picture.', 'Explore aggregate results when the poll’s results policy allows it. A fresh perspective is always welcome.'],
      ].map(([number, title, text]) => <li key={number}><span aria-hidden="true">{number}</span><div><h3>{title}</h3><p>{text}</p></div></li>)}</ol>
    </section>
  </>
}
