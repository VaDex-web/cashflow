import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Bar, BarChart, CartesianGrid, Cell, Legend, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { api } from '../api/client'
import { Empty, ErrorBox, Hint, Loading, SourceBadge } from '../components/ui'
import { fmtDay, fmtPct, fmtRub, fmtRubShort, parseDate } from '../lib/format'
import { useSession } from '../lib/session'
import { useAsync } from '../lib/useAsync'
import { NoCompany } from './Dashboard'

const DEV_THRESHOLD = 0.07

function weekLabel(p: string) {
  const a = parseDate(p)
  const b = new Date(a)
  b.setDate(b.getDate() + 6)
  const end = b.toLocaleDateString('ru-RU', { day: 'numeric', month: 'short' })
  return a.getMonth() === b.getMonth()
    ? `${a.getDate()}–${end}`
    : `${a.toLocaleDateString('ru-RU', { day: 'numeric', month: 'short' })} – ${end}`
}

export function PlanFact() {
  const { companyId } = useSession()
  const nav = useNavigate()
  const pf = useAsync(() => (companyId ? api.planFact(companyId) : Promise.resolve([])), [companyId])
  const ev = useAsync(() => (companyId ? api.events(companyId) : Promise.resolve([])), [companyId])
  const [kind, setKind] = useState<'in' | 'out'>('in')
  const [busy, setBusy] = useState(false)

  if (!companyId) return <NoCompany />
  if (pf.loading) return <Loading height={400} />
  if (pf.error) return <ErrorBox message={pf.error} onRetry={pf.reload} />

  const rows = pf.data ?? []
  if (!rows.length) {
    return (
      <div className="card">
        <Empty
          icon={
            <svg width="40" height="40" viewBox="0 0 24 24" fill="none" stroke="var(--text-3)" strokeWidth="1.5">
              <line x1="18" y1="20" x2="18" y2="10" />
              <line x1="12" y1="20" x2="12" y2="4" />
              <line x1="6" y1="20" x2="6" y2="14" />
            </svg>
          }
          title="Данные для план-факта накапливаются"
        >
          Сравнение прогноза с фактическими оборотами сформируется по итогам первой недели после построения прогноза.
        </Empty>
      </div>
    )
  }

  const data = rows.map((r) => {
    const plan = kind === 'in' ? r.planned_in : r.planned_out
    const fact = kind === 'in' ? r.actual_in : r.actual_out
    return { label: weekLabel(r.period), plan, fact, dev: plan ? (fact - plan) / plan : 0, row: r }
  })

  const avgPlan = data.reduce((s, d) => s + d.plan, 0) / (data.length || 1)
  const tinyPlan = (d: { plan: number }) => d.plan < avgPlan * 0.25
  const isBad = (d: { plan: number; fact: number; dev: number }) => {
    const diff = kind === 'in' ? d.plan - d.fact : d.fact - d.plan
    return tinyPlan(d) ? diff > avgPlan * 0.25 : diff > 0 && Math.abs(d.dev) > DEV_THRESHOLD
  }

  const totalPlanIn = rows.reduce((s, r) => s + r.planned_in, 0)
  const totalFactIn = rows.reduce((s, r) => s + r.actual_in, 0)
  const totalPlanOut = rows.reduce((s, r) => s + r.planned_out, 0)
  const totalFactOut = rows.reduce((s, r) => s + r.actual_out, 0)
  const overdue = (ev.data ?? []).filter((e) => e.status === 'overdue')
  const deviations = rows.flatMap((r) => r.deviations.map((d) => ({ ...d, period: r.period })))

  async function recalc() {
    setBusy(true)
    try {
      await api.forecast(companyId!, 30)
      nav('/')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="grid" style={{ gap: 20 }}>
      <div className="page-head" style={{ marginBottom: 0 }}>
        <div>
          <h1>План и факт</h1>
          <p>Сравнение прогнозных расчетов с фактически проведенными банковскими операциями по неделям.</p>
        </div>
      </div>

      <div className="grid-2">
        <Total title="Поступления" plan={totalPlanIn} fact={totalFactIn} goodIfMore />
        <Total title="Списания" plan={totalPlanOut} fact={totalFactOut} />
      </div>

      <section className="card">
        <div className="card-head">
          <div className="row" style={{ gap: 8, alignItems: 'center' }}>
            <h2>Динамика по неделям</h2>
            <Hint>
              «План» — расчетная величина модели на начало расчетной недели. «Факт» — фактические операции по выписке банка.
              Отклонения свыше {Math.round(DEV_THRESHOLD * 100)}% выделены цветом.
            </Hint>
          </div>
          <div className="seg">
            <button type="button" className={kind === 'in' ? 'on' : ''} onClick={() => setKind('in')}>
              Поступления
            </button>
            <button type="button" className={kind === 'out' ? 'on' : ''} onClick={() => setKind('out')}>
              Списания
            </button>
          </div>
        </div>

        <div style={{ height: 320 }}>
          <ResponsiveContainer>
            <BarChart data={data} margin={{ top: 12, right: 12, bottom: 0, left: 0 }} barGap={6}>
              <CartesianGrid stroke="var(--border-light)" vertical={false} />
              <XAxis dataKey="label" tick={{ fontSize: 12, fill: 'var(--text-3)' }} tickLine={false} axisLine={{ stroke: 'var(--border)' }} />
              <YAxis tickFormatter={fmtRubShort} tick={{ fontSize: 12, fill: 'var(--text-3)' }} tickLine={false} axisLine={false} width={72} />
              <Tooltip
                formatter={(v) => fmtRub(Number(v))}
                labelFormatter={(l) => `Неделя ${l}`}
                contentStyle={{
                  background: 'var(--surface)',
                  borderRadius: 10,
                  border: '1px solid var(--border)',
                  boxShadow: 'var(--shadow-popover)',
                }}
              />
              <Legend />
              <Bar dataKey="plan" name="План" fill="#D4D5DA" radius={[4, 4, 0, 0]} />
              <Bar dataKey="fact" name="Факт" radius={[4, 4, 0, 0]}>
                {data.map((d) => {
                  const bad = isBad(d)
                  return <Cell key={d.label} fill={bad ? 'var(--danger)' : 'var(--primary-active)'} />
                })}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        </div>

        <div className="table-wrap" style={{ marginTop: 16 }}>
          <table className="table table-stack num">
            <thead>
              <tr>
                <th>Период (неделя)</th>
                <th className="r">План</th>
                <th className="r">Факт</th>
                <th className="r">Отклонение</th>
              </tr>
            </thead>
            <tbody>
              {data.map((d) => {
                const bad = isBad(d)
                return (
                  <tr key={d.label} style={bad ? { background: 'var(--danger-bg)' } : undefined}>
                    <td style={{ fontWeight: 500 }}>{d.label}</td>
                    <td className="r">{fmtRub(d.plan)}</td>
                    <td className="r">{fmtRub(d.fact)}</td>
                    <td className="r" style={{ color: bad ? 'var(--danger)' : 'var(--text-2)', fontWeight: bad ? 600 : 400 }}>
                      {d.fact - d.plan >= 0 ? '+' : '−'}{fmtRub(Math.abs(d.fact - d.plan))}
                      {!tinyPlan(d) && ` (${d.dev >= 0 ? '+' : '−'}${fmtPct(Math.abs(d.dev))})`}
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      </section>

      <section className="card">
        <div className="card-head">
          <h2 style={{ margin: 0 }}>Анализ отклонений</h2>
          <button
            type="button"
            className="btn btn-lime"
            onClick={recalc}
            disabled={busy}
            style={{ display: 'inline-flex', alignItems: 'center', gap: 8 }}
          >
            <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <path d="M21.5 2v6h-6M21.34 15.57a10 10 0 1 1-.57-8.38l5.67-5.67" />
            </svg>
            {busy ? 'Пересчет…' : 'Пересчитать прогноз'}
          </button>
        </div>

        {overdue.length === 0 && deviations.length === 0 && (
          <Empty
            icon={
              <div
                style={{
                  width: 44,
                  height: 44,
                  borderRadius: '50%',
                  background: 'var(--primary-65)',
                  color: 'var(--primary-active)',
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                  margin: '0 auto',
                }}
              >
                <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
                  <polyline points="20 6 9 17 4 12" />
                </svg>
              </div>
            }
            title="Отклонений не зафиксировано"
          >
            Все запланированные операции прошли своевременно, расхождение в пределах погрешности модели.
          </Empty>
        )}

        <div className="grid" style={{ gap: 10 }}>
          {overdue.map((e) => (
            <div key={e.id} className="notice notice-err" style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
              <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" style={{ flexShrink: 0 }}>
                <circle cx="12" cy="12" r="10" />
                <polyline points="12 6 12 12 16 14" />
              </svg>
              <div style={{ flex: 1 }}>
                <b>Ожидаемый платёж не поступил в срок:</b> {e.counterparty} — {fmtRub(e.amount)}, ожидался {fmtDay(e.date)}.
                {e.note && <div className="small" style={{ marginTop: 2 }}>{e.note}</div>}
              </div>
              <SourceBadge s={e.source} />
            </div>
          ))}

          {deviations
            .filter((d) => !overdue.some((o) => o.id === d.event_id))
            .map((d) => (
              <div key={d.event_id + d.period} className="notice notice-warn" style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
                <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" style={{ flexShrink: 0 }}>
                  <circle cx="12" cy="12" r="10" />
                  <line x1="12" y1="8" x2="12" y2="12" />
                  <line x1="12" y1="16" x2="12.01" y2="16" />
                </svg>
                <span>
                  <b>Неделя {weekLabel(d.period)}:</b> {d.text}
                </span>
              </div>
            ))}
        </div>
      </section>
    </div>
  )
}

function Total({ title, plan, fact, goodIfMore }: { title: string; plan: number; fact: number; goodIfMore?: boolean }) {
  const dev = plan ? (fact - plan) / plan : 0
  const bad = goodIfMore ? dev < -DEV_THRESHOLD / 2 : dev > DEV_THRESHOLD / 2

  return (
    <div className="card" style={{ padding: '20px 22px' }}>
      <div className="small muted" style={{ fontWeight: 500 }}>{title} за учтенный период</div>
      <div className="row" style={{ marginTop: 8, gap: 20, alignItems: 'baseline' }}>
        <div>
          <div className="tiny" style={{ color: 'var(--text-3)' }}>План</div>
          <div className="num" style={{ fontSize: 22, fontWeight: 700, color: 'var(--text)' }}>{fmtRub(plan)}</div>
        </div>
        <div>
          <div className="tiny" style={{ color: 'var(--text-3)' }}>Факт</div>
          <div className="num" style={{ fontSize: 22, fontWeight: 700, color: 'var(--text)' }}>{fmtRub(fact)}</div>
        </div>
        <span className={`badge ${bad ? 'b-high' : 'b-low'}`}>
          {dev >= 0 ? '+' : ''}{fmtPct(dev)}
        </span>
      </div>
    </div>
  )
}
