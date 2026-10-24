import { useEffect, useRef, useState, type ReactNode } from 'react'
import type { EventSource, Severity } from '../types'

export function Hint({ children }: { children: ReactNode }) {
  const [open, setOpen] = useState(false)
  const ref = useRef<HTMLSpanElement>(null)
  useEffect(() => {
    if (!open) return
    const close = (e: MouseEvent) => { if (!ref.current?.contains(e.target as Node)) setOpen(false) }
    document.addEventListener('mousedown', close)
    return () => document.removeEventListener('mousedown', close)
  }, [open])
  return (
    <span className="hint" ref={ref} onMouseEnter={() => setOpen(true)} onMouseLeave={() => setOpen(false)}>
      <button type="button" className="hint-btn" aria-label="Как посчитано" onClick={() => setOpen((o) => !o)}>?</button>
      {open && <span className="hint-pop" role="tooltip">{children}</span>}
    </span>
  )
}

export function Loading({ height = 120, label = 'Загружаем…' }: { height?: number; label?: string }) {
  return <div className="skeleton" style={{ height }} aria-busy="true" aria-label={label} />
}

export function ErrorBox({ message, onRetry }: { message: string; onRetry?: () => void }) {
  return (
    <div className="notice notice-err" role="alert">
      <span>⚠️</span>
      <div style={{ flex: 1 }}>
        <b>Не получилось загрузить данные.</b> {message}
      </div>
      {onRetry && <button className="btn btn-sm btn-ghost" onClick={onRetry}>Повторить</button>}
    </div>
  )
}

export function Empty({ icon = '📭', title, children }: { icon?: string; title: string; children?: ReactNode }) {
  return (
    <div style={{ textAlign: 'center', padding: '32px 16px', color: 'var(--text-2)' }}>
      <div style={{ fontSize: 34 }}>{icon}</div>
      <h3 style={{ margin: '8px 0 4px', color: 'var(--text)' }}>{title}</h3>
      {children && <div className="small">{children}</div>}
    </div>
  )
}

export function Warnings({ items }: { items?: string[] }) {
  const [open, setOpen] = useState(false)
  if (!items?.length) return null
  if (items.length === 1) return <div className="notice notice-warn"><span>ℹ️</span><span>{items[0]}</span></div>
  return (
    <div className="notice notice-warn" style={{ display: 'block' }}>
      <button type="button" onClick={() => setOpen((o) => !o)} aria-expanded={open}
        style={{ border: 0, background: 'none', padding: 0, cursor: 'pointer', fontWeight: 600, color: 'inherit', textAlign: 'left' }}>
        ℹ️ Что учтено в прогнозе и замечания о данных ({items.length}) {open ? '▲' : '▼'}
      </button>
      {open && (
        <ul style={{ margin: '8px 0 0', paddingLeft: 22, display: 'grid', gap: 4 }}>
          {items.map((w) => <li key={w}>{w}</li>)}
        </ul>
      )}
    </div>
  )
}

export const SEVERITY_LABEL: Record<Severity, string> = { high: 'Высокий риск', medium: 'Есть риск', low: 'Небольшой риск' }

export function SeverityBadge({ s }: { s: Severity }) {
  return <span className={`badge b-${s}`}>● {SEVERITY_LABEL[s]}</span>
}

export const SOURCE_LABEL: Record<EventSource, string> = {
  bank: 'Банк', '1c': '1С', tax_calendar: 'Налоговый календарь', open_registry: 'Открытый реестр', manual: 'Вручную',
}
const SOURCE_COLOR: Record<EventSource, string> = {
  bank: '#0b3d2e', '1c': '#c62828', tax_calendar: '#2f6fb3', open_registry: '#7b4fb0', manual: '#6b7a71',
}
const SOURCE_ICON: Record<EventSource, string> = { bank: '🏦', '1c': '📒', tax_calendar: '🧾', open_registry: '📜', manual: '✍️' }

export function SourceBadge({ s }: { s: EventSource }) {
  return (
    <span className="badge" style={{ background: `${SOURCE_COLOR[s]}14`, color: SOURCE_COLOR[s], border: `1px solid ${SOURCE_COLOR[s]}33` }}>
      {SOURCE_ICON[s]} {SOURCE_LABEL[s]}
    </span>
  )
}
