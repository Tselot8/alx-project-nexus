import { Component } from 'react'
import type { ReactNode } from 'react'
import { Button, Card } from '../ui/components'

export class AppErrorBoundary extends Component<{ children: ReactNode }, { failed: boolean }> {
  state = { failed: false }
  static getDerivedStateFromError() { return { failed: true } }
  render() {
    if (this.state.failed) return <main className="container recovery"><Card>
      <p className="eyebrow">Let’s get you back</p><h1>Something interrupted this page.</h1>
      <p>Your next visit can start fresh.</p>
      <Button onClick={() => window.location.reload()}>Reload Project Nexus</Button>
    </Card></main>
    return this.props.children
  }
}
