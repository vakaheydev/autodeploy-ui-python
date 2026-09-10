import { NavLink, Outlet } from 'react-router-dom'
import { Boxes, CircleAlert, ClipboardList, History, Home, LoaderCircle, Moon, Puzzle, Search, Settings, Sparkles, Sun, X } from './Icons'
import { useEnvironment } from '../environment'
import { useTheme } from '../theme'
import { SearchableSelect } from './SearchableSelect'

const links = [
  { to: '/', label: 'Главная', icon: Home },
  { to: '/forms', label: 'Формы', icon: Boxes },
  { to: '/tickets', label: 'Заявки', icon: ClipboardList },
  { to: '/plugins', label: 'Плагины', icon: Puzzle },
  { to: '/search', label: 'Поиск', icon: Search },
  { to: '/runs', label: 'История', icon: History },
  { to: '/settings', label: 'Настройки', icon: Settings },
]

export function Shell() {
  const {
    environments,
    environment,
    environmentSwitching,
    environmentError,
    setEnvironment,
    dismissEnvironmentError,
  } = useEnvironment()
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
          <div className="environment-switcher">
            <span className="eyebrow">Рабочее окружение</span>
            <div className="environment-select-row">
              <SearchableSelect ariaLabel="Окружение" compact clearable={false} value={environment} onChange={(value) => void setEnvironment(value)} disabled={environmentSwitching} loading={environmentSwitching} options={environments.map((item) => ({ value: item.key, label: item.label }))} searchPlaceholder="Найти окружение…" />
              {environmentSwitching && <span className="environment-switch-progress" role="status"><LoaderCircle className="spin" size={15} /> Переключаю…</span>}
            </div>
            {environmentError && <div className="environment-switch-error" role="alert"><CircleAlert size={15} /><span>{environmentError}</span><button type="button" onClick={dismissEnvironmentError} aria-label="Закрыть ошибку"><X size={14} /></button></div>}
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
