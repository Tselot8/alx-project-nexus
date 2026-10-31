import { Link } from 'react-router'
import { Card } from '../ui/components'

export function Home() {
  return <>
    <section className="hero">
      <div><p className="eyebrow"><span className="status-dot" />A little curiosity goes a long way</p>
        <h1>Different voices.<br /><span className="text-blue">Clearer decisions.</span></h1>
        <p className="hero-description">A place for good questions and thoughtful answers. Bring people together, hear their perspectives, and see the bigger picture.</p>
        <div className="action-row"><Link to="/polls" className="button button--primary">Explore polls <span aria-hidden="true">↗</span></Link>
          <Link to="/polls/new" className="button button--secondary">Create a poll</Link></div>
        <p className="supporting-copy">Make space for every perspective.</p>
      </div>
      <Card className="signal-card">
        <span className="pill">A clearer signal</span>
        <div className="signal-graphic" aria-hidden="true"><div /><div /><div /><div /></div>
        <h2>Better questions.<br />Shared understanding.</h2>
        <p>From a quick check-in to the next big idea, start with the people who matter.</p>
        <span className="signal-caption"><span className="status-dot" />Ask · Share · Understand</span>
      </Card>
    </section>
    <section className="intro-section" aria-labelledby="possibilities"><div className="section-heading">
      <p className="eyebrow">Thoughtful by design</p><h2 id="possibilities">One question. More possibilities.</h2></div>
      <div className="feature-grid">{[
        ['01', 'Find your curiosity', 'Discover questions and perspectives beyond your own.'],
        ['02', 'Make yourself heard', 'Participate with confidence and revisit your choices while a poll is open.'],
        ['03', 'Bring people together', 'Create a focused space for feedback, privately or in the open.'],
      ].map(([number, title, text]) => <Card key={number}><span className="feature-number">{number}</span>
        <h3>{title}</h3><p>{text}</p></Card>)}</div>
    </section>
    <div className="foundation-note"><span className="pill">Early access</span><p>Accounts are ready. Poll discovery, voting, and creator tools are being prepared for the next release.</p></div>
  </>
}
