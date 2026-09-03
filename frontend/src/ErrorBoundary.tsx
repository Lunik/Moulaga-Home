import { Component, type ReactNode } from 'react'

import { Icon } from './ui'

interface Props {
  children: ReactNode
}

interface State {
  error: Error | null
}

export class ViewErrorBoundary extends Component<Props, State> {
  state: State = { error: null }

  static getDerivedStateFromError(error: Error): State {
    return { error }
  }

  render() {
    if (!this.state.error) return this.props.children
    return (
      <section className="view-error" role="alert">
        <span><Icon name="alert" /></span>
        <div>
          <h2>Cette vue n'a pas pu être affichée</h2>
          <p>{this.state.error.message || 'La réponse locale ne correspond pas au format attendu.'}</p>
          <button className="secondary-button" type="button" onClick={() => window.location.reload()}>
            <Icon name="refresh" />Recharger l'application
          </button>
        </div>
      </section>
    )
  }
}
