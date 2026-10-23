import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Bar, BarChart, CartesianGrid, Cell, Legend, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { api } from '../api/client'
import { Empty, ErrorBox, Hint, Loading, SourceBadge } from '../components/ui'
import { fmtDay, fmtPct, fmtRub, fmtRubShort, parseDate } from '../lib/format'
import { useSession } from '../lib/session'
import { useAsync } from '../lib/useAsync'
import { NoCompany } from './Dashboard'

const DEV_THRESHOLD = 0.07 // отклонение больше 7% подсвечиваем

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
  if (!rows.length) return <div className="card"><Empty icon="📊" title="Пока нечего сравнивать">План-факт появится, когда пройдёт хотя бы неделя после первого прогноза.</Empty></div>

  const data = rows.map((r) => {
    const plan = kind === 'in' ? r.planned_in : r.planned_out
    const fact = kind === 'in' ? r.actual_in : r.actual_out
    return { label: weekLabel(r.period), plan, fact, dev: plan ? (fact - plan) / plan : 0, row: r }
  })
  // Неделя с почти нулевым планом даёт бессмысленные проценты — там сравниваем только рубли
  const avgPlan = data.reduce((s, d) => s + d.plan, 0) / data.length
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
    <div className="grid" style={{ gap: 18 }}>
      <div className="page-head" style={{ marginBottom: 0 }}>
        <div>
          <h1>План и факт</h1>
          <p>Сравниваем, сколько денег ожидали и сколько пришло и ушло на самом деле.</p>
        </div>
      </div>

      <div className="grid-2">
        <Total title="Поступления" plan={totalPlanIn} fact={totalFactIn} goodIfMore />
        <Total title="Списания" plan={totalPlanOut} fact={totalFactOut} />
      </div>

      <section className="card">
        <div className="card-head">
          <div className="row" style={{ gap: 8 }}>
            <h2>По неделям</h2>
            <Hint>«План» — сколько мы прогнозировали в начале недели. «Факт» — что прошло по счёту. Красным выделены недели, где разница больше {Math.round(DEV_THRESHOLD * 100)}%.</Hint>
          </div>
          <div className="seg">
            <button className={kind === 'in' ? 'on' : ''} onClick={() => setKind('in')}>Поступления</button>
            <button className={kind === 'out' ? 'on' : ''} onClick={() => setKind('out')}>Списания</button>
          </div>
        </div>
        <div style={{ height: 300 }}>
          <ResponsiveContainer>
            <BarChart data={data} margin={{ top: 8, right: 8, bottom: 0, left: 0 }} barGap={4}>
              <CartesianGrid stroke="#e8ede5" vertical={false} />
              <XAxis dataKey="label" tick={{ fontSize: 12, fill: '#7a8a80' }} tickLine={false} axisLine={{ stroke: '#dfe6da' }} />
              <YAxis tickFormatter={fmtRubShort} tick={{ fontSize: 12, fill: '#7a8a80' }} tickLine={false} axisLine={false} width={72} />
              <Tooltip formatter={(v) => fmtRub(Number(v))} labelFormatter={(l) => `Неделя ${l}`} />
              <Legend />
              <Bar dataKey="plan" name="План" fill="#c9d6cd" radius={[6, 6, 0, 0]} />
              <Bar dataKey="fact" name="Факт" radius={[6, 6, 0, 0]}>
                {data.map((d) => {
                  const bad = isBad(d)
                  return <Cell key={d.label} fill={bad ? '#d23b3b' : '#11553f'} />
                })}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        </div>
        <div className="table-wrap" style={{ marginTop: 12 }}>
          <table className="table num">
            <thead><tr><th>Неделя</th><th className="r">План</th><th className="r">Факт</th><th className="r">Разница</th></tr></thead>
            <tbody>
              {data.map((d) => {
                const bad = isBad(d)
                return (
                  <tr key={d.label} style={bad ? { background: 'var(--red-bg)' } : undefined}>
                    <td>{d.label}</td>
                    <td className="r">{fmtRub(d.plan)}</td>
                    <td className="r">{fmtRub(d.fact)}</td>
                    <td className="r" style={{ color: bad ? 'var(--red)' : 'var(--text-2)', fontWeight: bad ? 650 : 400 }}>
                      {d.fact - d.plan >= 0 ? '+' : '−'}{fmtRub(Math.abs(d.fact - d.plan))}{!tinyPlan(d) && ` (${d.dev >= 0 ? '+' : '−'}${fmtPct(Math.abs(d.dev))})`}
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
          <h2>Что пошло не по плану</h2>
          <button className="btn btn-lime" onClick={recalc} disabled={busy}>{busy ? 'Пересчитываем…' : '🔄 Пересчитать прогноз'}</button>
        </div>
        {overdue.length === 0 && deviations.length === 0 && <Empty icon="✅" title="Всё по плану">Все ожидаемые платежи прошли в срок.</Empty>}
        <div className="grid" style={{ gap: 10 }}>
          {overdue.map((e) => (
            <div key={e.id} className="notice notice-err" style={{ alignItems: 'center' }}>
              <span>⏰</span>
              <div style={{ flex: 1 }}>
                <b>Ожидаемый платёж не пришёл в срок:</b> {e.counterparty} — {fmtRub(e.amount)}, ждали {fmtDay(e.date)}.
                {e.note && <div className="small">{e.note}</div>}
              </div>
              <SourceBadge s={e.source} />
            </div>
          ))}
          {deviations.filter((d) => !overdue.some((o) => o.id === d.event_id)).map((d) => (
            <div key={d.event_id + d.period} className="notice notice-warn"><span>⚠️</span><span><b>Неделя {weekLabel(d.period)}:</b> {d.text}</span></div>
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
    <div className="card">
      <div className="small muted">{title} за последние недели</div>
      <div className="row" style={{ marginTop: 6, gap: 18, alignItems: 'baseline' }}>
        <div><div className="tiny">План</div><div className="num" style={{ fontSize: 20, fontWeight: 650 }}>{fmtRub(plan)}</div></div>
        <div><div className="tiny">Факт</div><div className="num" style={{ fontSize: 20, fontWeight: 650 }}>{fmtRub(fact)}</div></div>
        <span className={`badge ${bad ? 'b-high' : 'b-low'}`}>{dev >= 0 ? '+' : ''}{fmtPct(dev)}</span>
      </div>
    </div>
  )
}

