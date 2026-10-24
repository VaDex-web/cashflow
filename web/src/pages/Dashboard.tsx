import { Link } from 'react-router-dom'
import { api } from '../api/client'
import { AlertsList } from '../components/AlertsList'
import { BalanceChart, ChartLegend } from '../components/BalanceChart'
import { forecastToday, RiskCard } from '../components/RiskCard'
import { Empty, ErrorBox, Hint, Loading, SourceBadge, Warnings } from '../components/ui'
import { fmtDateTime, fmtDay, fmtRub } from '../lib/format'
import { useSession } from '../lib/session'
import { useAsync } from '../lib/useAsync'
import type { EventSource } from '../types'

export function Dashboard() {
  const { companyId } = useSession()
  const fc = useAsync(() => (companyId ? api.forecast(companyId, 30) : Promise.resolve(null)), [companyId])
  const ev = useAsync(() => (companyId ? api.events(companyId) : Promise.resolve([])), [companyId])

  if (!companyId) return <NoCompany />

  if (fc.loading && !fc.data) {
    return (
      <div className="grid">
        <div className="notice notice-info"><span>⏳</span><span>Считаем прогноз: проигрываем тысячи вариантов ближайшего месяца. В первый раз это занимает до 20 секунд.</span></div>
        <Loading height={150} /><Loading height={380} />
      </div>
    )
  }
  if (fc.error || !fc.data) return <ErrorBox message={fc.error ?? 'Нет данных'} onRetry={fc.reload} />

  const f = fc.data
  if (!f.daily.length) return <Empty icon="📉" title="Пока нечего показать">В выписке слишком мало операций, чтобы построить прогноз.</Empty>

  const today = forecastToday(f)
  const startBal = f.current_balance
  const end = f.daily[f.daily.length - 1]
  const min = f.daily.reduce((a, b) => (b.balance_p50 < a.balance_p50 ? b : a))

  return (
    <div className="grid" style={{ gap: 18 }}>
      <div className="page-head" style={{ marginBottom: 0 }}>
        <div>
          <h1 style={{ fontSize: 22 }}>Деньги на ближайшие {f.horizon_days} дней</h1>
          <p className="small">Прогноз обновлён {fmtDateTime(f.generated_at)}</p>
        </div>
        <Link to="/scenarios" className="btn btn-ghost">🔮 А что если…</Link>
      </div>

      <RiskCard fc={f} />
      <Warnings items={f.warnings} />

      <div className="grid-3">
        {startBal != null && (
          <Kpi label={`Сейчас на счёте (${fmtDay(today)})`} value={fmtRub(startBal)}
            hint="Остаток на конец последнего дня в загруженной выписке." />
        )}
        <Kpi label={`Самый низкий остаток — ${fmtDay(min.date)}`} value={fmtRub(min.balance_p50)} danger={min.balance_p50 < 0}
          hint="Наименьший ожидаемый остаток за весь срок прогноза. Если число отрицательное — в этот день денег не хватит на все платежи." />
        <Kpi label={`Через ${f.horizon_days} дней (${fmtDay(end.date)})`} value={fmtRub(end.balance_p50)} danger={end.balance_p50 < 0}
          sub={`возможно от ${fmtRub(end.balance_low)} до ${fmtRub(end.balance_high)}`}
          hint="Ожидаемый остаток в последний день прогноза и диапазон, в который он попадёт с вероятностью около 80%." />
      </div>

      <div className="grid-main">
        <section className="card">
          <div className="card-head">
            <div className="row" style={{ gap: 8 }}>
              <h2>Остаток на счёте по дням</h2>
              <Hint>
                Линия — ожидаемый остаток: сколько денег будет на счёте в конце дня, если всё пойдёт как обычно.
                Светлая полоса — возможный диапазон: с вероятностью около 80% остаток окажется внутри неё.
                Учтены регулярные платежи (зарплата, аренда, налоги), ожидаемые счета и обычная выручка.
              </Hint>
            </div>
          </div>
          <BalanceChart
            base={{ daily: f.daily, label: 'Ожидаемый остаток', color: '#11553f' }}
            events={ev.data ?? []}
            risks={f.risks}
            start={startBal != null ? { date: today, balance: startBal } : undefined}
            comfort={f.comfort_balance}
          />
          <ChartLegend items={[
            { color: '#11553f', label: 'Ожидаемый остаток' },
            { color: '#11553f', label: 'Возможный диапазон', band: true },
          ]} />
        </section>

        <section className="card">
          <div className="card-head"><h2>Предупреждения</h2></div>
          <AlertsList risks={f.risks} daily={f.daily} comfort={f.comfort_balance} />
        </section>
      </div>

      {f.sources_used.length > 0 && (
        <section className="card">
          <div className="card-head">
            <h3>На чём основан прогноз</h3>
            <Link to="/events" className="small">Управлять источниками →</Link>
          </div>
          <div className="row" style={{ gap: 6 }}>
            {f.sources_used.map((s) => <SourceBadge key={s} s={s as EventSource} />)}
          </div>
        </section>
      )}
    </div>
  )
}

function Kpi({ label, value, sub, hint, danger }: { label: string; value: string; sub?: string; hint: string; danger?: boolean }) {
  return (
    <div className="card" style={{ padding: 16 }}>
      <div className="row small muted" style={{ gap: 6, flexWrap: 'nowrap' }}>
        <span>{label}</span>
        <Hint>{hint}</Hint>
      </div>
      <div className="num" style={{ fontSize: 26, fontWeight: 700, marginTop: 4, color: danger ? 'var(--red)' : undefined }}>{value}</div>
      {sub && <div className="tiny">{sub}</div>}
    </div>
  )
}

export function NoCompany() {
  return (
    <div className="card">
      <Empty icon="📄" title="Сначала загрузите выписку">
        Прогноз строится по истории операций на счёте.
        <div style={{ marginTop: 14 }}><Link className="btn btn-lime" to="/upload">Загрузить выписку</Link></div>
      </Empty>
    </div>
  )
}
