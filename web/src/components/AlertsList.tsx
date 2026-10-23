import type { DailyPoint, Risk } from '../types'
import { riskKind, shortfallText } from '../lib/risk'
import { fmtDayWeek, fmtPct } from '../lib/format'
import { Empty, Hint, SeverityBadge } from './ui'

export function AlertsList({ risks, daily = [], comfort }: { risks: Risk[]; daily?: DailyPoint[]; comfort?: number }) {
  if (!risks.length) return <Empty icon="✅" title="Предупреждений нет">В ближайший месяц остаток не опускается ниже нуля.</Empty>
  return (
    <div className="grid" style={{ gap: 12 }}>
      {[...risks].sort((a, b) => a.date.localeCompare(b.date)).map((r) => (
        <article key={r.date} style={{ border: '1px solid var(--border)', borderLeft: `4px solid ${r.severity === 'high' ? 'var(--red)' : r.severity === 'medium' ? 'var(--amber)' : 'var(--ok)'}`, borderRadius: 12, padding: 14 }}>
          <div className="row" style={{ justifyContent: 'space-between' }}>
            <b>{fmtDayWeek(r.date)}</b>
            <SeverityBadge s={r.severity} />
          </div>
          <div className="row" style={{ marginTop: 6, gap: 6 }}>
            {riskKind(r) === 'below_comfort'
              ? <span>Останется <b>{shortfallText(r, daily, comfort).main}</b></span>
              : shortfallText(r, daily, comfort).main
                ? <span>Может не хватить <b className="num">{shortfallText(r, daily, comfort).main}</b></span>
                : <span>Денег может не хватить</span>}
            <span className="muted">· вероятность {fmtPct(r.probability)}</span>
            <Hint>Вероятность — доля смоделированных вариантов будущего, в которых в этот день денег на счёте {riskKind(r) === 'below_comfort' ? 'меньше комфортного минимума' : 'меньше нуля'}.</Hint>
          </div>
          {shortfallText(r, daily, comfort).sub && <p className="small" style={{ marginTop: 6 }}>{shortfallText(r, daily, comfort).sub}</p>}
          <p className="small muted" style={{ marginTop: 8 }}>{r.reason}</p>
          {r.recommendations.length > 0 && (
            <>
              <div className="small" style={{ fontWeight: 650, marginTop: 10 }}>Что можно сделать:</div>
              <ol className="small" style={{ margin: '4px 0 0', paddingLeft: 18, display: 'grid', gap: 4 }}>
                {r.recommendations.map((t) => <li key={t}>{t}</li>)}
              </ol>
            </>
          )}
        </article>
      ))}
    </div>
  )
}
