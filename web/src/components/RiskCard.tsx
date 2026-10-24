import type { ReactNode } from 'react'
import type { ForecastResult } from '../types'
import { daysBetween, fmtDay, fmtPct, fmtRub, inDays, toISO, parseDate } from '../lib/format'
import { Hint } from './ui'
import { mainRisk, riskKind, shortfallText } from '../lib/risk'

export { mainRisk }

export function forecastToday(fc: ForecastResult): string {
  if (fc.as_of) return fc.as_of
  const d = parseDate(fc.daily[0].date)
  d.setDate(d.getDate() - 1)
  return toISO(d)
}

interface ToneConfig {
  bg: string
  border: string
  accent: string
  title: string
  badgeCls: string
  iconBg: string
  icon: ReactNode
}

const TONE: Record<'high' | 'medium' | 'low' | 'comfort' | 'ok', ToneConfig> = {
  high: {
    bg: '#ffffff',
    border: '#f8d7da',
    accent: '#d70f00',
    title: 'Кассовый разрыв',
    badgeCls: 'b-high',
    iconBg: '#fcedec',
    icon: (
      <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="#d70f00" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
        <path d="m21.73 18-8-14a2 2 0 0 0-3.48 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.73-3Z" />
        <line x1="12" y1="9" x2="12" y2="13" />
        <line x1="12" y1="17" x2="12.01" y2="17" />
      </svg>
    ),
  },
  medium: {
    bg: '#ffffff',
    border: '#feea9f',
    accent: '#d97706',
    title: 'Риск нехватки средств',
    badgeCls: 'b-medium',
    iconBg: '#fffbeb',
    icon: (
      <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="#d97706" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
        <circle cx="12" cy="12" r="10" />
        <line x1="12" y1="8" x2="12" y2="12" />
        <line x1="12" y1="16" x2="12.01" y2="16" />
      </svg>
    ),
  },
  comfort: {
    bg: '#ffffff',
    border: '#feea9f',
    accent: '#d97706',
    title: 'Запас денег на исходе',
    badgeCls: 'b-medium',
    iconBg: '#fffbeb',
    icon: (
      <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="#d97706" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
        <circle cx="12" cy="12" r="10" />
        <line x1="12" y1="8" x2="12" y2="12" />
        <line x1="12" y1="16" x2="12.01" y2="16" />
      </svg>
    ),
  },
  low: {
    bg: '#ffffff',
    border: '#bddebb',
    accent: '#398233',
    title: 'Внимание к балансу',
    badgeCls: 'b-low',
    iconBg: '#f0f7f0',
    icon: (
      <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="#398233" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
        <circle cx="12" cy="12" r="10" />
        <polyline points="12 6 12 12 14 14" />
      </svg>
    ),
  },
  ok: {
    bg: '#ffffff',
    border: '#bddebb',
    accent: '#50b848',
    title: 'Баланс в норме',
    badgeCls: 'b-low',
    iconBg: '#f0f7f0',
    icon: (
      <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="#50b848" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
        <path d="M22 11.08V12a10 10 0 1 1-5.93-9.14" />
        <polyline points="22 4 12 14.01 9 11.01" />
      </svg>
    ),
  },
}

export function RiskCard({ fc }: { fc: ForecastResult }) {
  const r = mainRisk(fc.risks)
  const today = forecastToday(fc)
  const kind = r ? riskKind(r) : null
  const toneKey = !r ? 'ok' : kind === 'below_comfort' ? 'comfort' : r.severity
  const tone = TONE[toneKey]
  const amount = r ? shortfallText(r, fc.daily, fc.comfort_balance) : null
  const minDay = fc.daily.reduce((a, b) => (b.balance_p50 < a.balance_p50 ? b : a))

  return (
    <section
      className="card"
      style={{
        background: tone.bg,
        borderColor: tone.border,
        borderLeftWidth: 5,
        borderLeftColor: tone.accent,
        padding: '24px 28px',
      }}
      aria-live="polite"
    >
      <div style={{ display: 'flex', gap: 18, alignItems: 'flex-start' }}>
        <div
          style={{
            width: 44,
            height: 44,
            borderRadius: 12,
            background: tone.iconBg,
            display: 'grid',
            placeItems: 'center',
            flexShrink: 0,
            marginTop: 2,
          }}
        >
          {tone.icon}
        </div>

        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap' }}>
            <span
              style={{
                fontSize: 12,
                fontWeight: 700,
                color: tone.accent,
                textTransform: 'uppercase',
                letterSpacing: '.06em',
              }}
            >
              {tone.title}
            </span>
            {r && (
              <span className={`badge ${tone.badgeCls}`} style={{ fontSize: 13, padding: '3px 10px' }}>
                Вероятность {fmtPct(r.probability)}
              </span>
            )}
            {r && (
              <Hint>
                Мы много раз проиграли ближайший месяц с разными задержками оплат и колебаниями выручки.
                В {fmtPct(r.probability)} вариантов остаток {fmtDay(r.date)} уходит{' '}
                {kind === 'below_comfort' ? 'ниже вашего комфортного минимума' : 'ниже нуля'}.
                {kind === 'below_comfort'
                  ? ' Комфортный минимум — запас на счёте, ниже которого вам неспокойно (по умолчанию — расходы примерно за неделю).'
                  : ' Крупная сумма — сколько не хватит при ожидаемом ходе событий, «до …» — сколько нужно, чтобы хватило в 9 случаях из 10.'}
              </Hint>
            )}
            {fc.risks.length > 1 && (
              <span className="small muted">
                и ещё {fc.risks.length - 1} {fc.risks.length - 1 === 1 ? 'предупреждение' : 'предупреждения'} ниже
              </span>
            )}
          </div>

          {r ? (
            <>
              <h1 style={{ fontSize: 'clamp(20px, 2.6vw, 28px)', marginTop: 8, lineHeight: 1.3, fontWeight: 700 }}>
                {cap(inDays(daysBetween(today, r.date)))}, {fmtDay(r.date)},{' '}
                {kind === 'below_comfort'
                  ? 'на счёте может остаться'
                  : amount!.main
                  ? 'дефицит составит'
                  : 'денег может не хватить'}{' '}
                {amount!.main && (
                  <span style={{ color: tone.accent, whiteSpace: 'nowrap' }}>{amount!.main}</span>
                )}
              </h1>

              {amount!.sub && (
                <p className="muted" style={{ marginTop: 6, fontSize: 14 }}>
                  {amount!.sub}
                </p>
              )}

              <p style={{ marginTop: 10, maxWidth: 820, color: 'var(--text-2)', fontSize: 15, lineHeight: 1.5 }}>
                {r.reason}
              </p>

              {r.recommendations[0] && (
                <div
                  style={{
                    marginTop: 16,
                    padding: '12px 16px',
                    borderRadius: 10,
                    background: 'var(--surface-subtle)',
                    border: '1px solid var(--border-light)',
                    display: 'flex',
                    alignItems: 'flex-start',
                    gap: 10,
                  }}
                >
                  <svg
                    width="18"
                    height="18"
                    viewBox="0 0 24 24"
                    fill="none"
                    stroke="var(--primary-hover)"
                    strokeWidth="2"
                    strokeLinecap="round"
                    strokeLinejoin="round"
                    style={{ flexShrink: 0, marginTop: 2 }}
                  >
                    <path d="M12 2v4" />
                    <path d="m4.93 4.93 2.83 2.83" />
                    <path d="M2 12h4" />
                    <path d="m4.93 19.07 2.83-2.83" />
                    <path d="M16 12a4 4 0 1 1-8 0 4 4 0 0 1 8 0z" />
                    <path d="M12 18v4" />
                    <path d="m19.07 19.07-2.83-2.83" />
                    <path d="M22 12h-4" />
                    <path d="m19.07 4.93-2.83 2.83" />
                  </svg>
                  <div>
                    <span style={{ fontWeight: 600, fontSize: 13, color: 'var(--text)', display: 'block', marginBottom: 2 }}>
                      Рекомендация:
                    </span>
                    <span style={{ fontSize: 14, color: 'var(--text-2)' }}>
                      {r.recommendations[0]}
                    </span>
                  </div>
                </div>
              )}
            </>
          ) : (
            <>
              <h1 style={{ fontSize: 'clamp(20px, 2.6vw, 28px)', marginTop: 8, fontWeight: 700 }}>
                В ближайшие {fc.horizon_days} дней средств на счёте достаточно
              </h1>
              <p style={{ marginTop: 8, color: 'var(--text-2)', fontSize: 15 }}>
                Минимальный ожидаемый остаток прогнозируется {fmtDay(minDay.date)} — около{' '}
                <b className="num" style={{ color: 'var(--ok-accent)' }}>{fmtRub(minDay.balance_p50)}</b>.
              </p>
            </>
          )}
        </div>
      </div>
    </section>
  )
}

const cap = (s: string) => s.charAt(0).toUpperCase() + s.slice(1)
