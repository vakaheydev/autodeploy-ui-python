import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { api } from '../api'
import { AppWindow, Boxes, History, Search, ServerCog, Sparkles } from '../components/Icons'
import { Copilot } from '../components/Copilot'

interface Status { state: string; address: string; message: string }

const modules = [
  { to: '/search', icon: Search, title: 'Поиск', text: 'Найдите API и приложения во всех окружениях.', accent: 'blue' },
  { to: '/forms', icon: Boxes, title: 'AutoDeploy', text: 'Создавайте и изменяйте сущности через управляемые формы.', accent: 'violet' },
  { to: '/runs', icon: History, title: 'История', text: 'Возвращайтесь к предыдущим операциям и их результатам.', accent: 'amber' },
  { to: '/opencode', icon: ServerCog, title: 'OpenCode', text: 'Подключение, модели и техническое состояние AI.', accent: 'teal' },
]

export function HomePage() {
  const [status, setStatus] = useState<Status | null>(null)
  useEffect(() => {
    let active = true
    const poll = () => api<Status>('/api/v1/opencode/status')
      .then((value) => active && setStatus(value))
      .catch(() => active && setStatus(null))
    void poll()
    const timer = window.setInterval(poll, 5000)
    return () => { active = false; window.clearInterval(timer) }
  }, [])

  return (
    <div className="page-stack">
      <section className="hero-panel">
        <div>
          <span className="hero-kicker"><Sparkles size={15} /> Единое рабочее пространство</span>
          <h1>Gravitee AutoDeploy</h1>
          <p>Формы, справочники, поиск и AI-помощник — в одном локальном веб-приложении.</p>
        </div>
        <div className="hero-visual"><AppWindow size={42} /></div>
      </section>

      {status?.state === 'ready' && <Copilot />}

      <section>
        <div className="section-heading"><div><span className="eyebrow">Модули</span><h2>Выберите действие</h2></div></div>
        <div className="module-grid">
          {modules.map(({ to, icon: Icon, title, text, accent }) => (
            <Link to={to} className="module-card" key={to}>
              <span className={`module-icon ${accent}`}><Icon /></span>
              <div><h3>{title}</h3><p>{text}</p></div>
              <span className="module-arrow">→</span>
            </Link>
          ))}
        </div>
      </section>
    </div>
  )
}
