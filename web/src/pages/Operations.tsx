import { useMemo, useState } from 'react'
import { Bar, BarChart, Cell, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { api } from '../api/client'
import { Empty, ErrorBox, Hint, Loading } from '../components/ui'
import { fmtDay, fmtDayShort, fmtPct, fmtRub, fmtRubShort, plural } from '../lib/format'
import { useSession } from '../lib/session'
import { useAsync } from '../lib/useAsync'
import type { Direction } from '../types'
import { NoCompany } from './Dashboard'

const PALETTE = ['#11553f', '#6fa62a', '#2f6fb3', '#d98a00', '#7b4fb0', '#c2477a', '#3a8f8f', '#8a6d3b', '#7a8a80']
const PAGE = 50

function periodText(days: number) {
  if (days === 1) return 'каждый день'
  if (days <= 8) return 'каждую неделю'
  if (days <= 16) return 'раз в 2 недели'
  if (days <= 35) return 'каждый месяц'
  if (days <= 100) return 'раз в квартал'
  return `раз в ${days} ${plural(days, 'день', 'дня', 'дней')}`
}

export function Operations() {
  const { companyId } = useSession()
  const cat = useAsync(() => (companyId ? api.categories(companyId) : Promise.resolve(null)), [companyId])
  const rec = useAsync(() => (companyId ? api.recurring(companyId) : Promise.resolve([])), [companyId])
  const [dir, setDir] = useState<Direction>('out')
  const [q, setQ] = useState('')
  const [category, setCategory] = useState<string | null>(null)
  const [limit, setLimit] = useState(PAGE)

  const txs = useMemo(() => {
    const s = q.trim().toLowerCase()
    return (cat.data?.transactions ?? []).filter((t) =>
      (!category || t.category === category) &&
      (!s || `${t.counterparty_name} ${t.purpose} ${t.category ?? ''} ${t.counterparty_inn}`.toLowerCase().includes(s)))
  }, [cat.data, q, category])

  if (!companyId) return <NoCompany />

  const summary = (cat.data?.summary ?? []).filter((c) => c.direction === dir).sort((a, b) => b.total - a.total)
  const total = summary.reduce((s, c) => s + c.total, 0)

  return (
    <div className="grid" style={{ gap: 18 }}>
      <div className="page-head" style={{ marginBottom: 0 }}>
        <div>
          <h1>Операции</h1>
          <p>Куда уходят и откуда приходят деньги. Категории мы определили автоматически по назначению платежа.</p>
        </div>
      </div>

      <div className="grid-main">
        <section className="card">
          <div className="card-head">
            <div className="row" style={{ gap: 8 }}>
              <h2>{dir === 'out' ? 'На что тратим' : 'Откуда приходят деньги'}</h2>
              <Hint>Сумма операций по каждой категории за период выписки. Нажмите на строку, чтобы увидеть операции этой категории.</Hint>
            </div>
            <div className="seg">
              <button className={dir === 'out' ? 'on' : ''} onClick={() => { setDir('out'); setCategory(null) }}>Расходы</button>
              <button className={dir === 'in' ? 'on' : ''} onClick={() => { setDir('in'); setCategory(null) }}>Поступления</button>
            </div>
          </div>
          {cat.loading && <Loading height={260} />}
          {cat.error && <ErrorBox message={cat.error} onRetry={cat.reload} />}
          {summary.length > 0 && (
            <div style={{ height: Math.max(180, summary.length * 40) }}>
              <ResponsiveContainer>
                <BarChart data={summary} layout="vertical" margin={{ left: 0, right: 70, top: 0, bottom: 0 }}
                  onClick={(e) => { const p = (e as { activeLabel?: string })?.activeLabel; if (p) setCategory((c) => (c === p ? null : p)) }}>
                  <XAxis type="number" hide />
                  <YAxis type="category" dataKey="category" width={170} tick={{ fontSize: 13, fill: '#13241c' }} tickLine={false} axisLine={false} />
                  <Tooltip formatter={(v) => fmtRub(Number(v))} cursor={{ fill: '#eef7e1' }} />
                  <Bar dataKey="total" name="Сумма" radius={[0, 6, 6, 0]} style={{ cursor: 'pointer' }}
                    label={{ position: 'right', fontSize: 12, fill: '#4b5d53', formatter: (v: unknown) => `${fmtRubShort(Number(v))} · ${fmtPct(Number(v) / total)}` }}>
                    {summary.map((c, i) => <Cell key={c.category} fill={PALETTE[i % PALETTE.length]} fillOpacity={!category || category === c.category ? 1 : 0.3} />)}
                  </Bar>
                </BarChart>
              </ResponsiveContainer>
            </div>
          )}
          {!cat.loading && !cat.error && summary.length === 0 && <Empty title="Нет операций" />}
        </section>

        <section className="card">
          <div className="card-head">
            <div className="row" style={{ gap: 8 }}>
              <h2>Регулярные платежи</h2>
              <Hint>Платежи, которые повторяются с похожей суммой и периодичностью. «Уверенность» — насколько стабильно они повторялись в прошлом.</Hint>
            </div>
          </div>
          {rec.loading && <Loading height={260} />}
          {rec.error && <ErrorBox message={rec.error} onRetry={rec.reload} />}
          <div className="grid" style={{ gap: 0 }}>
            {[...(rec.data ?? [])].sort((a, b) => a.next_date.localeCompare(b.next_date)).map((r) => (
              <div key={r.name} style={{ padding: '10px 0', borderBottom: '1px solid var(--border)' }}>
                <div className="row" style={{ justifyContent: 'space-between', flexWrap: 'nowrap' }}>
                  <span style={{ fontWeight: 600 }}>{r.name}</span>
                  <b className="num" style={{ whiteSpace: 'nowrap', color: r.direction === 'in' ? 'var(--ok)' : 'var(--text)' }}>{r.direction === 'in' ? '+' : '−'}{fmtRub(r.amount_avg)}</b>
                </div>
                <div className="tiny">{periodText(r.period_days)} · следующий {fmtDay(r.next_date)} · уверенность {fmtPct(r.confidence)}</div>
              </div>
            ))}
          </div>
          {!rec.loading && !rec.error && !rec.data?.length && <Empty icon="🔁" title="Регулярных платежей не нашли">Нужна выписка хотя бы за 2–3 месяца.</Empty>}
        </section>
      </div>

      <section className="card">
        <div className="card-head">
          <h2>Все операции {category && <span className="badge b-neutral" style={{ marginLeft: 6 }}>{category} <button onClick={() => setCategory(null)} style={{ border: 0, background: 'none', cursor: 'pointer', padding: 0 }}>✕</button></span>}</h2>
          <input className="input" placeholder="Поиск: контрагент, назначение, ИНН" value={q} onChange={(e) => { setQ(e.target.value); setLimit(PAGE) }} style={{ maxWidth: 320 }} />
        </div>
        {txs.length === 0 && !cat.loading && <Empty icon="🔍" title="Ничего не нашли" />}
        {txs.length > 0 && (
          <div className="table-wrap">
            <table className="table">
              <thead><tr><th>Дата</th><th>Контрагент и назначение</th><th>Категория</th><th className="r">Сумма</th><th className="r">Остаток</th></tr></thead>
              <tbody>
                {txs.slice(0, limit).map((t, i) => (
                  <tr key={i}>
                    <td className="num" style={{ whiteSpace: 'nowrap' }}>{fmtDayShort(t.date)}</td>
                    <td>
                      <div>{t.counterparty_name || <span className="muted">Контрагент не указан</span>}</div>
                      <div className="tiny">{t.purpose || 'Без назначения'}</div>
                    </td>
                    <td>
                      <span className="badge b-neutral">{t.category ?? '—'}</span>
                      {t.category_confidence != null && t.category_confidence < 0.7 && <div className="tiny" title="Категория определена неуверенно">не уверены</div>}
                    </td>
                    <td className="r num" style={{ whiteSpace: 'nowrap', fontWeight: 600, color: t.direction === 'in' ? 'var(--ok)' : 'var(--text)' }}>
                      {t.direction === 'in' ? '+' : '−'}{fmtRub(t.amount, true)}
                    </td>
                    <td className="r num muted" style={{ whiteSpace: 'nowrap', color: t.balance_eod < 0 ? 'var(--red)' : undefined }}>{fmtRub(t.balance_eod)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        {txs.length > limit && (
          <div style={{ textAlign: 'center', marginTop: 12 }}>
            <button className="btn btn-ghost" onClick={() => setLimit((l) => l + PAGE)}>Показать ещё ({txs.length - limit})</button>
          </div>
        )}
      </section>
    </div>
  )
}
