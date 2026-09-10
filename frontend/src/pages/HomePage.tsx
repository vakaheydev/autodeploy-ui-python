import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { api } from '../api'
import { Boxes, ClipboardList, History, Puzzle, Search, ServerCog, Sparkles } from '../components/Icons'
import { Copilot } from '../components/Copilot'

interface Status { state: string; address: string; message: string }

const modules = [
  { to: '/search', icon: Search, title: 'Поиск', text: 'Найдите API и приложения во всех окружениях.', accent: 'blue' },
  { to: '/forms', icon: Boxes, title: 'AutoDeploy', text: 'Создавайте и изменяйте сущности через управляемые формы.', accent: 'violet' },
  { to: '/tickets', icon: ClipboardList, title: 'Заявки', text: 'Работайте с текущими заявками и корпоративными действиями.', accent: 'blue' },
  { to: '/plugins', icon: Puzzle, title: 'Плагины', text: 'Открывайте корпоративные рабочие страницы и инструменты.', accent: 'teal' },
  { to: '/runs', icon: History, title: 'История', text: 'Возвращайтесь к предыдущим операциям и их результатам.', accent: 'amber' },
  { to: '/settings?section=OpenCode', icon: ServerCog, title: 'OpenCode', text: 'Подключение, модели и техническое состояние AI в настройках.', accent: 'teal' },
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
        <h1 className="hero-title"><Sparkles aria-hidden="true" /> Gravitee AutoDeploy</h1>
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
