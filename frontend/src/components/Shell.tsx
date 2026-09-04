import { NavLink, Outlet } from 'react-router-dom'
import { Boxes, History, Home, Search, ServerCog, Sparkles } from './Icons'
import { useEnvironment } from '../environment'

const links = [
  { to: '/', label: 'Главная', icon: Home },
  { to: '/forms', label: 'Формы', icon: Boxes },
  { to: '/search', label: 'Поиск', icon: Search },
  { to: '/runs', label: 'История', icon: History },
  { to: '/opencode', label: 'OpenCode', icon: ServerCog },
]

export function Shell() {
  const { environments, environment, setEnvironment } = useEnvironment()
  return (
    <div className="app-shell">
      <aside className="sidebar">
        <div className="brand">
          <span className="brand-mark"><Sparkles size={19} /></span>
          <span><strong>Gravitee</strong><small>AutoDeploy</small></span>
        </div>
        <nav aria-label="Основная навигация">
          {links.map(({ to, label, icon: Icon }) => (
            <NavLink key={to} to={to} end={to === '/'} className={({ isActive }) => isActive ? 'active' : ''}>
              <Icon size={18} />
              <span>{label}</span>
            </NavLink>
          ))}
        </nav>
        <div className="sidebar-foot">
          <span className="status-dot online" />
          <span>Локальный сервер</span>
          <small>v1.0.0</small>
        </div>
      </aside>
      <main className="main-area">
        <header className="topbar">
          <div>
            <span className="eyebrow">Рабочее окружение</span>
            <div className="select-wrap compact">
              <select
                aria-label="Окружение"
                value={environment}
                onChange={(event) => setEnvironment(event.target.value)}
              >
                {environments.map((item) => <option value={item.key} key={item.key}>{item.label}</option>)}
              </select>
            </div>
          </div>
          <div className="topbar-note">
            <span className="status-dot online" /> API подключён
          </div>
        </header>
        <div className="page-container"><Outlet /></div>
      </main>
    </div>
  )
}
