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
      <div className="grid" style={{ gap: 18 }}>
        <div className="notice notice-info" style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
          <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" style={{ flexShrink: 0 }}>
            <circle cx="12" cy="12" r="10" />
            <polyline points="12 6 12 12 16 14" />
          </svg>
          <span>Считаем прогноз: проигрываем тысячи вариантов ближайшего месяца. В первый раз это занимает до 20 секунд.</span>
        </div>
        <Loading height={150} />
        <Loading height={380} />
      </div>
    )
  }

  if (fc.error || !fc.data) return <ErrorBox message={fc.error ?? 'Нет данных'} onRetry={fc.reload} />

  const f = fc.data
  if (!f.daily.length) {
    return (
      <Empty title="Пока нечего показать">
        В выписке слишком мало операций, чтобы построить прогноз.
      </Empty>
    )
  }

  const today = forecastToday(f)
  const startBal = f.current_balance
  const end = f.daily[f.daily.length - 1]
  const min = f.daily.reduce((a, b) => (b.balance_p50 < a.balance_p50 ? b : a))

  return (
    <div className="grid" style={{ gap: 20 }}>
      <div className="page-head" style={{ marginBottom: 0 }}>
        <div>
          <h1>Деньги на ближайшие {f.horizon_days} дней</h1>
          <p className="small">Прогноз обновлён {fmtDateTime(f.generated_at)}</p>
        </div>
        <Link to="/scenarios" className="btn btn-ghost" style={{ display: 'inline-flex', alignItems: 'center', gap: 8 }}>
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <line x1="4" x2="20" y1="21" y2="21" />
            <line x1="4" x2="20" y1="3" y2="3" />
            <line x1="4" x2="20" y1="12" y2="12" />
            <circle cx="9" cy="21" r="2" />
            <circle cx="15" cy="3" r="2" />
            <circle cx="12" cy="12" r="2" />
          </svg>
          Смоделировать «Что если»
        </Link>
      </div>

      <RiskCard fc={f} />
      <Warnings items={f.warnings} />

      <div className="grid-3">
        {startBal != null && (
          <Kpi
            label={`Сейчас на счёте (${fmtDay(today)})`}
            value={fmtRub(startBal)}
            hint="Остаток на конец последнего дня в загруженной выписке."
          />
        )}
        <Kpi
          label={`Самый низкий остаток (${fmtDay(min.date)})`}
          value={fmtRub(min.balance_p50)}
          danger={min.balance_p50 < 0}
          hint="Наименьший ожидаемый остаток за весь срок прогноза. При отрицательном значении возникнет дефицит средств."
        />
        <Kpi
          label={`Через ${f.horizon_days} дней (${fmtDay(end.date)})`}
          value={fmtRub(end.balance_p50)}
          danger={end.balance_p50 < 0}
          sub={`диапазон от ${fmtRub(end.balance_low)} до ${fmtRub(end.balance_high)}`}
          hint="Ожидаемый остаток в последний день прогноза и диапазон возможных значений (80% доверительный интервал)."
        />
      </div>

      <div className="grid-main">
        <section className="card">
          <div className="card-head">
            <div className="row" style={{ gap: 8 }}>
              <h2>Остаток на счёте по дням</h2>
              <Hint>
                Линия — ожидаемый остаток: сколько денег будет на счёте в конце дня при обычном темпе бизнеса.
                Светлая полоса — возможный доверительный диапазон (вероятность около 80%).
                Красная пунктирная линия — нулевой порог; область ниже нуля означает кассовый разрыв.
              </Hint>
            </div>
          </div>
          <BalanceChart
            base={{ daily: f.daily, label: 'Ожидаемый остаток', color: 'var(--primary)' }}
            events={ev.data ?? []}
            risks={f.risks}
            start={startBal != null ? { date: today, balance: startBal } : undefined}
            comfort={f.comfort_balance}
          />
          <ChartLegend
            items={[
              { color: 'var(--primary)', label: 'Ожидаемый остаток' },
              { color: 'var(--primary)', label: 'Возможный диапазон (80%)', band: true },
            ]}
          />
        </section>

        <section className="card">
          <div className="card-head">
            <h2>Предупреждения</h2>
          </div>
          <AlertsList risks={f.risks} daily={f.daily} comfort={f.comfort_balance} />
        </section>
      </div>

      {f.sources_used.length > 0 && (
        <section className="card" style={{ padding: '16px 20px' }}>
          <div className="card-head" style={{ marginBottom: 10 }}>
            <span style={{ fontSize: 12, fontWeight: 700, color: 'var(--text-3)', textTransform: 'uppercase', letterSpacing: '0.04em' }}>
              Подключенные источники данных
            </span>
            <Link to="/events" className="small" style={{ color: 'var(--primary-hover)', fontWeight: 600 }}>
              Управлять источниками →
            </Link>
          </div>
          <div className="row" style={{ gap: 8 }}>
            {f.sources_used.map((s) => (
              <SourceBadge key={s} s={s as EventSource} />
            ))}
          </div>
        </section>
      )}
    </div>
  )
}

function Kpi({ label, value, sub, hint, danger }: { label: string; value: string; sub?: string; hint: string; danger?: boolean }) {
  return (
    <div
      className="card"
      style={{
        padding: '18px 20px',
        borderLeft: danger ? '4px solid var(--danger)' : '1px solid var(--border)',
      }}
    >
      <div className="row small muted" style={{ gap: 6, flexWrap: 'nowrap', justifyContent: 'space-between' }}>
        <span style={{ color: 'var(--text-2)', fontWeight: 500 }}>{label}</span>
        <Hint>{hint}</Hint>
      </div>
      <div
        className="num"
        style={{
          fontSize: 24,
          fontWeight: 700,
          marginTop: 6,
          color: danger ? 'var(--danger)' : 'var(--text)',
          letterSpacing: '-0.02em',
        }}
      >
        {value}
      </div>
      {sub && <div className="tiny" style={{ marginTop: 4, color: 'var(--text-3)' }}>{sub}</div>}
    </div>
  )
}

export function NoCompany() {
  const { setCompany } = useSession()
  return (
    <div className="card" style={{ padding: '48px 24px', textAlign: 'center' }}>
      <Empty title="Загрузите выписку для построения прогноза">
        <p style={{ maxWidth: 480, margin: '8px auto 20px', color: 'var(--text-2)' }}>
          Прогноз строится на основе истории операций по счёту. Загрузите файл CSV или откройте готовую модель бизнеса.
        </p>
        <div className="row" style={{ justifyContent: 'center', gap: 12 }}>
          <button className="btn btn-lime" onClick={() => setCompany('demo-yuzhny-vkus')}>
            Загрузить демо-данные
          </button>
          <Link className="btn btn-ghost" to="/upload">
            Загрузить CSV-файл
          </Link>
        </div>
      </Empty>
    </div>
  )
}
