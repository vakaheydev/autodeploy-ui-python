import { Component, ErrorInfo, ReactNode } from 'react'

interface Props { children: ReactNode }
interface State { failed: boolean }

export class ErrorBoundary extends Component<Props, State> {
  state: State = { failed: false }

  static getDerivedStateFromError(): State {
    return { failed: true }
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    // The API keeps authoritative operational logs.  This console entry is
    // intentionally metadata-only and does not render a stack trace to users.
    console.error('Frontend render failed', error.name, info.componentStack)
  }

  render() {
    if (!this.state.failed) return this.props.children
    return (
      <main className="app-crash" role="alert">
        <div className="app-crash-mark">!</div>
        <span className="eyebrow">Интерфейс остановлен</span>
        <h1>Не удалось отобразить страницу</h1>
        <p>Данные формы не отправлялись. Обновите интерфейс; Python-сервер продолжает работать.</p>
        <div className="button-row">
          <button className="button primary" onClick={() => window.location.reload()}>Перезагрузить</button>
          <a className="button secondary" href="/">На главную</a>
        </div>
      </main>
    )
  }
}
