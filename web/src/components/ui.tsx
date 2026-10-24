import { useEffect, useRef, useState, type ReactNode } from 'react'
import type { EventSource, Severity } from '../types'

export function Hint({ children }: { children: ReactNode }) {
  const [open, setOpen] = useState(false)
  const ref = useRef<HTMLSpanElement>(null)

  useEffect(() => {
    if (!open) return
    const close = (e: MouseEvent) => {
      if (!ref.current?.contains(e.target as Node)) setOpen(false)
    }
    document.addEventListener('mousedown', close)
    return () => document.removeEventListener('mousedown', close)
  }, [open])

  return (
    <span className="hint" ref={ref} onMouseEnter={() => setOpen(true)} onMouseLeave={() => setOpen(false)}>
      <button type="button" className="hint-btn" aria-label="Как посчитано" onClick={() => setOpen((o) => !o)}>
        ?
      </button>
      {open && (
        <span className="hint-pop" role="tooltip">
          {children}
        </span>
      )}
    </span>
  )
}

export function Loading({ height = 120, label = 'Загружаем…' }: { height?: number; label?: string }) {
  return <div className="skeleton" style={{ height }} aria-busy="true" aria-label={label} />
}

export function ErrorBox({ message, onRetry }: { message: string; onRetry?: () => void }) {
  return (
    <div className="notice notice-err" role="alert" style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
      <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" style={{ flexShrink: 0 }}>
        <circle cx="12" cy="12" r="10" />
        <line x1="12" y1="8" x2="12" y2="12" />
        <line x1="12" y1="16" x2="12.01" y2="16" />
      </svg>
      <div style={{ flex: 1 }}>
        <b style={{ marginRight: 6 }}>Не удалось загрузить данные.</b>
        <span>{message}</span>
      </div>
      {onRetry && (
        <button className="btn btn-sm btn-ghost" onClick={onRetry}>
          Повторить
        </button>
      )}
    </div>
  )
}

export function Empty({
  icon,
  title,
  children,
}: {
  icon?: ReactNode
  title: string
  children?: ReactNode
}) {
  return (
    <div style={{ textAlign: 'center', padding: '36px 16px', color: 'var(--text-2)' }}>
      {icon ? (
        <div style={{ marginBottom: 12, display: 'flex', justifyContent: 'center', fontSize: typeof icon === 'string' ? 32 : undefined }}>
          {icon}
        </div>
      ) : (
        <svg
          width="44"
          height="44"
          viewBox="0 0 24 24"
          fill="none"
          stroke="var(--text-3)"
          strokeWidth="1.5"
          strokeLinecap="round"
          strokeLinejoin="round"
          style={{ margin: '0 auto 12px', display: 'block' }}
        >
          <rect x="2" y="4" width="20" height="16" rx="2" />
          <path d="m22 7-8.97 5.7a1.94 1.94 0 0 1-2.06 0L2 7" />
        </svg>
      )}
      <h3 style={{ margin: '0 0 6px', color: 'var(--text)', fontSize: 16 }}>{title}</h3>
      {children && <div className="small" style={{ color: 'var(--text-2)' }}>{children}</div>}
    </div>
  )
}

export function Warnings({ items }: { items?: string[] }) {
  const [open, setOpen] = useState(false)
  if (!items?.length) return null

  if (items.length === 1) {
    return (
      <div className="notice notice-warn" style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" style={{ flexShrink: 0 }}>
          <circle cx="12" cy="12" r="10" />
          <line x1="12" y1="16" x2="12" y2="12" />
          <line x1="12" y1="8" x2="12.01" y2="8" />
        </svg>
        <span>{items[0]}</span>
      </div>
    )
  }

  return (
    <div className="notice notice-warn" style={{ display: 'block' }}>
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        aria-expanded={open}
        style={{
          border: 0,
          background: 'none',
          padding: 0,
          cursor: 'pointer',
          fontWeight: 600,
          color: 'inherit',
          textAlign: 'left',
          display: 'flex',
          alignItems: 'center',
          gap: 8,
          width: '100%',
        }}
      >
        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" style={{ flexShrink: 0 }}>
          <circle cx="12" cy="12" r="10" />
          <line x1="12" y1="16" x2="12" y2="12" />
          <line x1="12" y1="8" x2="12.01" y2="8" />
        </svg>
        <span style={{ flex: 1 }}>Что учтено в прогнозе и замечания о данных ({items.length})</span>
        <span>{open ? '▲' : '▼'}</span>
      </button>
      {open && (
        <ul style={{ margin: '10px 0 0', paddingLeft: 28, display: 'grid', gap: 6 }}>
          {items.map((w) => (
            <li key={w}>{w}</li>
          ))}
        </ul>
      )}
    </div>
  )
}

export const SEVERITY_LABEL: Record<Severity, string> = {
  high: 'Высокий риск',
  medium: 'Есть риск',
  low: 'Низкий риск',
}

export function SeverityBadge({ s }: { s: Severity }) {
  return <span className={`badge b-${s}`}>● {SEVERITY_LABEL[s]}</span>
}

export const SOURCE_LABEL: Record<EventSource, string> = {
  bank: 'Банк',
  '1c': '1С',
  tax_calendar: 'Налоговый календарь',
  open_registry: 'Открытый реестр',
  manual: 'Вручную',
}

const SOURCE_COLOR: Record<EventSource, string> = {
  bank: '#285C24',
  '1c': '#C62828',
  tax_calendar: '#1877F2',
  open_registry: '#7B4FB0',
  manual: '#555558',
}

function SourceIcon({ s }: { s: EventSource }) {
  const size = 13
  switch (s) {
    case 'bank':
      return (
        <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
          <path d="M3 21h18M3 10h18M5 10v11M19 10v11M9 10v11M14 10v11M12 3 2 10h20Z" />
        </svg>
      )
    case '1c':
      return (
        <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
          <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
          <polyline points="14 2 14 8 20 8" />
          <line x1="16" y1="13" x2="8" y2="13" />
          <line x1="16" y1="17" x2="8" y2="17" />
          <polyline points="10 9 9 9 8 9" />
        </svg>
      )
    case 'tax_calendar':
      return (
        <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
          <rect x="3" y="4" width="18" height="18" rx="2" ry="2" />
          <line x1="16" y1="2" x2="16" y2="6" />
          <line x1="8" y1="2" x2="8" y2="6" />
          <line x1="3" y1="10" x2="21" y2="10" />
        </svg>
      )
    case 'open_registry':
      return (
        <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
          <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z" />
        </svg>
      )
    case 'manual':
      return (
        <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
          <path d="M11 4H4a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7" />
          <path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z" />
        </svg>
      )
  }
}

export function SourceBadge({ s }: { s: EventSource }) {
  const color = SOURCE_COLOR[s] ?? '#555558'
  return (
    <span
      className="badge"
      style={{
        background: `${color}10`,
        color,
        border: `1px solid ${color}30`,
        display: 'inline-flex',
        alignItems: 'center',
        gap: 5,
        fontSize: 12,
        fontWeight: 500,
      }}
    >
      <SourceIcon s={s} />
      <span>{SOURCE_LABEL[s] ?? s}</span>
    </span>
  )
}
