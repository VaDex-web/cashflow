import type { ForecastResult, Risk } from '../types'
import { daysBetween, fmtDay, fmtPct, fmtRub, inDays, toISO, parseDate } from '../lib/format'
import { Hint } from './ui'

export function forecastToday(fc: ForecastResult): string {
  if (fc.as_of) return fc.as_of
  const d = parseDate(fc.daily[0].date)
  d.setDate(d.getDate() - 1)
  return toISO(d)
}

/** Главный риск — самый ранний среди самых серьёзных */
export function mainRisk(risks: Risk[]): Risk | undefined {
  const order = { high: 0, medium: 1, low: 2 }
  return [...risks].sort((a, b) => order[a.severity] - order[b.severity] || a.date.localeCompare(b.date))[0]
}

const TONE = {
  high: { bg: 'linear-gradient(135deg, #fff1f1 0%, #ffe3e3 100%)', border: '#f3b4b4', dot: '#d23b3b', title: 'Внимание: может не хватить денег' },
  medium: { bg: 'linear-gradient(135deg, #fff8e8 0%, #ffefcc 100%)', border: '#f0d08a', dot: '#d98a00', title: 'Есть риск нехватки денег' },
  low: { bg: 'linear-gradient(135deg, #f2faea 0%, #e3f3d0 100%)', border: '#c2e19b', dot: '#6fa62a', title: 'Денег хватает, но есть слабое место' },
  ok: { bg: 'linear-gradient(135deg, #f2faea 0%, #e3f3d0 100%)', border: '#c2e19b', dot: '#2f8f4e', title: 'Всё в порядке' },
}

export function RiskCard({ fc }: { fc: ForecastResult }) {
  const r = mainRisk(fc.risks)
  const today = forecastToday(fc)
  const tone = TONE[r?.severity ?? 'ok']
  const minDay = fc.daily.reduce((a, b) => (b.balance_p50 < a.balance_p50 ? b : a))

  return (
    <section className="card" style={{ background: tone.bg, borderColor: tone.border, padding: '22px 24px' }} aria-live="polite">
      <div className="row" style={{ gap: 14, alignItems: 'flex-start', flexWrap: 'nowrap' }}>
        <Light color={tone.dot} />
        <div style={{ flex: 1, minWidth: 0 }}>
          <div className="small" style={{ fontWeight: 650, color: tone.dot, textTransform: 'uppercase', letterSpacing: '.04em' }}>{tone.title}</div>
          {r ? (
            <>
              <h1 style={{ fontSize: 'clamp(22px, 3vw, 32px)', marginTop: 6, lineHeight: 1.25 }}>
                {cap(inDays(daysBetween(today, r.date)))}, {fmtDay(r.date)}, может не хватить{' '}
                <span style={{ color: tone.dot, whiteSpace: 'nowrap' }}>{fmtRub(r.shortfall_amount)}</span>
              </h1>
              <div className="row" style={{ marginTop: 10, gap: 8 }}>
                <span className="badge" style={{ background: '#fff', color: tone.dot, fontSize: 14, padding: '5px 12px' }}>
                  Вероятность {fmtPct(r.probability)}
                </span>
                <Hint>
                  Мы много раз проиграли ближайший месяц с разными задержками оплат и колебаниями выручки.
                  В {fmtPct(r.probability)} вариантов остаток {fmtDay(r.date)} уходит ниже нуля.
                  Сумма — сколько не хватит в самый трудный день при ожидаемом ходе событий.
                </Hint>
                {fc.risks.length > 1 && <span className="small muted">и ещё {fc.risks.length - 1} {fc.risks.length - 1 === 1 ? 'риск' : 'риска'} ниже</span>}
              </div>
              <p style={{ marginTop: 12, maxWidth: 760 }}>{r.reason}</p>
              {r.recommendations[0] && (
                <p style={{ marginTop: 8, fontWeight: 600 }}>👉 {r.recommendations[0]}</p>
              )}
            </>
          ) : (
            <>
              <h1 style={{ fontSize: 'clamp(22px, 3vw, 32px)', marginTop: 6 }}>
                В ближайшие {fc.horizon_days} дней денег должно хватить
              </h1>
              <p style={{ marginTop: 10 }}>
                Самый низкий остаток ожидается {fmtDay(minDay.date)} — около <b>{fmtRub(minDay.balance_p50)}</b>.
              </p>
            </>
          )}
        </div>
      </div>
    </section>
  )
}

function Light({ color }: { color: string }) {
  const lamp = (c: string, on: boolean) => (
    <span style={{ width: 14, height: 14, borderRadius: '50%', background: on ? c : '#d9ddd6', boxShadow: on ? `0 0 10px ${c}` : 'none' }} />
  )
  return (
    <div aria-hidden style={{ display: 'grid', gap: 6, padding: '8px 7px', background: '#1d2a24', borderRadius: 14, marginTop: 4 }}>
      {lamp('#d23b3b', color === '#d23b3b')}
      {lamp('#f0b400', color === '#d98a00')}
      {lamp('#5cc04a', color !== '#d23b3b' && color !== '#d98a00')}
    </div>
  )
}

const cap = (s: string) => s.charAt(0).toUpperCase() + s.slice(1)
