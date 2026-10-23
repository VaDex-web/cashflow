import { NavLink, Outlet } from 'react-router-dom'
import { USE_MOCK } from '../api/client'
import { useSession } from '../lib/session'

const NAV = [
  { to: '/', label: 'Главная', short: 'Главная', icon: '🏠' },
  { to: '/scenarios', label: 'Что если', short: 'Что если', icon: '🔮' },
  { to: '/plan-fact', label: 'План и факт', short: 'План-факт', icon: '📊' },
  { to: '/events', label: 'Платежи и источники', short: 'Платежи', icon: '📅' },
  { to: '/operations', label: 'Операции', short: 'Операции', icon: '🧾' },
  { to: '/quality', label: 'Качество прогноза', short: 'Качество', icon: '🎯' },
  { to: '/upload', label: 'Загрузить выписку', short: 'Выписка', icon: '⬆️' },
]

function Brand() {
  return (
    <div className="brand">
      <div className="brand-mark">₽</div>
      <div>
        Денежный прогноз
        <small>для малого бизнеса · Центр-Инвест</small>
      </div>
    </div>
  )
}

export function Layout() {
  const { logout } = useSession()
  return (
    <div className="app">
      <aside className="sidebar">
        <Brand />
        <nav className="nav">
          {NAV.map((n) => (
            <NavLink key={n.to} to={n.to} end={n.to === '/'}>
              <span className="nav-ico">{n.icon}</span>
              {n.label}
            </NavLink>
          ))}
        </nav>
        <div className="sidebar-foot">
          {USE_MOCK && <span>Демо-режим: тестовые данные</span>}
          <button className="btn btn-sm btn-ghost" style={{ color: '#cfe2d6', borderColor: '#2b5e4a' }} onClick={logout}>Выйти</button>
        </div>
      </aside>
      <header className="mobile-bar">
        <div className="brand-mark">₽</div>
        <b>Денежный прогноз</b>
        <span className="spacer" />
        <button className="btn btn-sm btn-ghost" style={{ color: '#fff', borderColor: '#2b5e4a' }} onClick={logout}>Выйти</button>
      </header>
      <main className="main">
        <Outlet />
      </main>
      <nav className="mobile-nav">
        {NAV.map((n) => (
          <NavLink key={n.to} to={n.to} end={n.to === '/'}>
            <span style={{ fontSize: 18 }}>{n.icon}</span>
            {n.short}
          </NavLink>
        ))}
      </nav>
    </div>
  )
}
