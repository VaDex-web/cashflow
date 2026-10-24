import type { DailyPoint, Risk } from '../types'
import { riskKind, shortfallText } from '../lib/risk'
import { fmtDayWeek, fmtPct } from '../lib/format'
import { Empty, Hint, SeverityBadge } from './ui'

export function AlertsList({
  risks,
  daily = [],
  comfort,
}: {
  risks: Risk[]
  daily?: DailyPoint[]
  comfort?: number
}) {
  if (!risks.length) {
    return (
      <Empty
        icon={
          <div
            style={{
              width: 48,
              height: 48,
              borderRadius: '50%',
              background: 'var(--primary-65)',
              color: 'var(--primary-active)',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
            }}
          >
            <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
              <polyline points="20 6 9 17 4 12" />
            </svg>
          </div>
        }
        title="Предупреждений нет"
      >
        В ближайшие 30 дней прогнозный остаток стабильно выше нуля, кассовых разрывов не ожидается.
      </Empty>
    )
  }

  return (
    <div className="grid" style={{ gap: 12 }}>
      {[...risks].sort((a, b) => a.date.localeCompare(b.date)).map((r) => {
        const isHigh = r.severity === 'high'
        const isMed = r.severity === 'medium'
        const borderAccent = isHigh ? 'var(--danger)' : isMed ? 'var(--warning)' : 'var(--ok)'
        const kind = riskKind(r)
        const text = shortfallText(r, daily, comfort)

        return (
          <article
            key={r.date}
            style={{
              border: '1px solid var(--border)',
              borderLeft: `4px solid ${borderAccent}`,
              background: 'var(--surface)',
              borderRadius: 'var(--radius-md)',
              padding: '14px 16px',
            }}
          >
            <div className="row" style={{ justifyContent: 'space-between', alignItems: 'center' }}>
              <div style={{ fontWeight: 600, color: 'var(--text)', fontSize: 14 }}>
                {fmtDayWeek(r.date)}
              </div>
              <SeverityBadge s={r.severity} />
            </div>

            <div className="row" style={{ marginTop: 6, gap: 6, alignItems: 'center' }}>
              {kind === 'below_comfort' ? (
                <span style={{ color: 'var(--text)', fontSize: 14 }}>
                  Останется: <b className="num" style={{ fontWeight: 700 }}>{text.main}</b>
                </span>
              ) : text.main ? (
                <span style={{ color: 'var(--text)', fontSize: 14 }}>
                  Дефицит: <b className="num" style={{ color: isHigh ? 'var(--danger)' : 'var(--text)', fontWeight: 700 }}>{text.main}</b>
                </span>
              ) : (
                <span style={{ color: 'var(--text)', fontSize: 14 }}>Денег может не хватить</span>
              )}
              <span style={{ color: 'var(--text-3)' }}>·</span>
              <span style={{ color: 'var(--text-2)', fontSize: 13 }}>вероятность {fmtPct(r.probability)}</span>
              <Hint>
                Вероятность — доля смоделированных вариантов будущего, в которых в этот день денег на счёте{' '}
                {kind === 'below_comfort' ? 'меньше комфортного минимума' : 'меньше нуля'}.
              </Hint>
            </div>

            {text.sub && (
              <p className="tiny muted" style={{ marginTop: 4 }}>
                {text.sub}
              </p>
            )}

            <p className="small" style={{ marginTop: 6, color: 'var(--text-2)', lineHeight: 1.45 }}>
              {r.reason}
            </p>

            {r.recommendations.length > 0 && (
              <div style={{ marginTop: 10, paddingTop: 8, borderTop: '1px solid var(--border-light)' }}>
                <div className="tiny muted" style={{ fontWeight: 600, textTransform: 'uppercase', letterSpacing: '0.04em', marginBottom: 4 }}>
                  Что можно сделать:
                </div>
                <ul className="small" style={{ margin: 0, paddingLeft: 16, display: 'grid', gap: 3, color: 'var(--text-2)' }}>
                  {r.recommendations.map((t) => (
                    <li key={t}>{t}</li>
                  ))}
                </ul>
              </div>
            )}
          </article>
        )
      })}
    </div>
  )
}
