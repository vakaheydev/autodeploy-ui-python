import { NavLink, Outlet } from 'react-router-dom'
import { Boxes, History, Home, Moon, Search, ServerCog, Settings, Sparkles, Sun } from './Icons'
import { useEnvironment } from '../environment'
import { useTheme } from '../theme'
import { SearchableSelect } from './SearchableSelect'

const links = [
  { to: '/', label: 'Главная', icon: Home },
  { to: '/forms', label: 'Формы', icon: Boxes },
  { to: '/search', label: 'Поиск', icon: Search },
  { to: '/runs', label: 'История', icon: History },
  { to: '/opencode', label: 'OpenCode', icon: ServerCog },
  { to: '/settings', label: 'Настройки', icon: Settings },
]

export function Shell() {
  const { environments, environment, setEnvironment } = useEnvironment()
  const { theme, toggleTheme } = useTheme()
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
            <SearchableSelect ariaLabel="Окружение" compact clearable={false} value={environment} onChange={setEnvironment} options={environments.map((item) => ({ value: item.key, label: item.label }))} searchPlaceholder="Найти окружение…" />
          </div>
          <div className="topbar-actions">
            <button className="icon-button theme-toggle" onClick={toggleTheme} aria-label={theme === 'light' ? 'Включить тёмную тему' : 'Включить светлую тему'} title={theme === 'light' ? 'Тёмная тема' : 'Светлая тема'}>{theme === 'light' ? <Moon size={17} /> : <Sun size={17} />}</button>
            <div className="topbar-note"><span className="status-dot online" /> API подключён</div>
          </div>
        </header>
        <div className="page-container"><Outlet /></div>
      </main>
    </div>
  )
}
