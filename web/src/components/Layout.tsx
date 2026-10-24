import type { ReactNode } from 'react'
import { NavLink, Outlet } from 'react-router-dom'
import { api, USE_MOCK } from '../api/client'
import { useSession } from '../lib/session'
import { useAsync } from '../lib/useAsync'

interface NavItem {
  to: string
  label: string
  short: string
  icon: ReactNode
}

const NAV: NavItem[] = [
  {
    to: '/',
    label: 'Главная',
    short: 'Главная',
    icon: (
      <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
        <path d="m3 9 9-7 9 7v11a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z" />
        <polyline points="9 22 9 12 15 12 15 22" />
      </svg>
    ),
  },
  {
    to: '/scenarios',
    label: 'Что если',
    short: 'Что если',
    icon: (
      <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
        <line x1="4" x2="20" y1="21" y2="21" />
        <line x1="4" x2="20" y1="3" y2="3" />
        <line x1="4" x2="20" y1="12" y2="12" />
        <circle cx="9" cy="21" r="2" />
        <circle cx="15" cy="3" r="2" />
        <circle cx="12" cy="12" r="2" />
      </svg>
    ),
  },
  {
    to: '/plan-fact',
    label: 'План и факт',
    short: 'План-факт',
    icon: (
      <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
        <line x1="18" x2="18" y1="20" y2="10" />
        <line x1="12" x2="12" y1="20" y2="4" />
        <line x1="6" x2="6" y1="20" y2="14" />
      </svg>
    ),
  },
  {
    to: '/events',
    label: 'Платежи и источники',
    short: 'Платежи',
    icon: (
      <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
        <rect width="18" height="18" x="3" y="4" rx="2" ry="2" />
        <line x1="16" y1="2" x2="16" y2="6" />
        <line x1="8" y1="2" x2="8" y2="6" />
        <line x1="3" y1="10" x2="21" y2="10" />
      </svg>
    ),
  },
  {
    to: '/operations',
    label: 'Операции',
    short: 'Операции',
    icon: (
      <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
        <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
        <polyline points="14 2 14 8 20 8" />
        <line x1="16" x2="8" y1="13" y2="13" />
        <line x1="16" x2="8" y1="17" y2="17" />
        <polyline points="10 9 9 9 8 9" />
      </svg>
    ),
  },
  {
    to: '/quality',
    label: 'Качество прогноза',
    short: 'Качество',
    icon: (
      <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
        <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z" />
        <path d="m9 12 2 2 4-4" />
      </svg>
    ),
  },
  {
    to: '/upload',
    label: 'Загрузить выписку',
    short: 'Выписка',
    icon: (
      <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
        <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />
        <polyline points="17 8 12 3 7 8" />
        <line x1="12" x2="12" y1="3" y2="15" />
      </svg>
    ),
  },
]

function Brand() {
  return (
    <div className="brand">
      <img src="/logo.svg" alt="Денежный прогноз" className="brand-logo-img" style={{ width: 32, height: 32, borderRadius: 8 }} />
      <div className="brand-meta">
        <span className="brand-title">Денежный прогноз</span>
        <span className="brand-sub">Центр-Инвест</span>
      </div>
    </div>
  )
}

export function Layout() {
  const { logout, companyId } = useSession()
  const me = useAsync(() => (companyId ? api.me() : Promise.resolve(null)), [companyId])
  const companyTitle = companyId
    ? me.data?.company_name || `Компания ${companyId.split('-')[0].toUpperCase()}`
    : 'Счёт не выбран'

  return (
    <div className="app">
      <aside className="sidebar">
        <Brand />

        <div className="sidebar-company-card">
          <div className="sidebar-company-avatar">
            {companyTitle.replace(/^(ООО|ИП|АО|ПАО|Компания)\s*[«"]?/i, '').slice(0, 1).toUpperCase() || 'К'}
          </div>
          <div className="sidebar-company-info">
            <div className="sidebar-company-name" title={companyTitle}>
              {companyTitle}
            </div>
            <div className="sidebar-company-status">
              {companyId ? 'Расчётный счёт активен' : 'Ожидает загрузки выписки'}
            </div>
          </div>
        </div>

        <nav className="nav">
          {NAV.map((n) => (
            <NavLink key={n.to} to={n.to} end={n.to === '/'}>
              <span className="nav-icon">{n.icon}</span>
              <span>{n.label}</span>
            </NavLink>
          ))}
        </nav>

        <div className="sidebar-foot">
          {USE_MOCK && (
            <div className="sidebar-demo-badge">
              Демо-режим: тестовые данные
            </div>
          )}
          <button
            type="button"
            className="btn btn-sm btn-ghost"
            style={{ width: '100%', justifyContent: 'center' }}
            onClick={logout}
          >
            Выйти
          </button>
        </div>
      </aside>

      <header className="mobile-bar">
        <img src="/logo.svg" alt="Денежный прогноз" style={{ height: 26, width: 26, borderRadius: 6 }} />
        <b style={{ fontSize: 14, color: 'var(--text)', fontWeight: 650 }}>Денежный прогноз</b>
        <span className="spacer" />
        <button
          type="button"
          className="btn btn-sm btn-ghost"
          onClick={logout}
        >
          Выйти
        </button>
      </header>

      <main className="main">
        <Outlet />
      </main>

      <nav className="mobile-nav">
        {NAV.map((n) => (
          <NavLink key={n.to} to={n.to} end={n.to === '/'}>
            <span className="nav-icon">{n.icon}</span>
            <span>{n.short}</span>
          </NavLink>
        ))}
      </nav>
    </div>
  )
}
