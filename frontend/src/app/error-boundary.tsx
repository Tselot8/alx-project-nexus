import { Component } from 'react'
import type { ReactNode } from 'react'
import { Button, Card } from '../ui/components'
import { BallotArtwork } from '../ui/illustrations'

export class AppErrorBoundary extends Component<{ children: ReactNode }, { failed: boolean }> {
  state = { failed: false }
  static getDerivedStateFromError() { return { failed: true } }
  render() {
    if (this.state.failed) return <main className="container recovery"><Card className="support-page"><div>
      <p className="eyebrow">Let’s get you back</p><h1>Something interrupted this page.</h1>
      <p>Your next visit can start fresh.</p>
      <Button onClick={() => window.location.reload()}>Reload Project Nexus</Button></div><BallotArtwork compact />
    </Card></main>
    return this.props.children
  }
}
