import { useMemo, useState } from 'react'
import { Bar, BarChart, Cell, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { api } from '../api/client'
import { Empty, ErrorBox, Hint, Loading } from '../components/ui'
import { fmtDay, fmtDayShort, fmtPct, fmtRub, fmtRubShort, plural } from '../lib/format'
import { useSession } from '../lib/session'
import { useAsync } from '../lib/useAsync'
import type { Direction } from '../types'
import { NoCompany } from './Dashboard'

const PALETTE = ['#50B848', '#398233', '#2AABEE', '#FBA100', '#7B4FB0', '#00A389', '#E05D5D', '#5C6B73', '#285C24']
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
    return (cat.data?.transactions ?? []).filter(
      (t) =>
        (!category || t.category === category) &&
        (!s || `${t.counterparty_name} ${t.purpose} ${t.category ?? ''} ${t.counterparty_inn}`.toLowerCase().includes(s)),
    )
  }, [cat.data, q, category])

  if (!companyId) return <NoCompany />

  const summary = (cat.data?.summary ?? []).filter((c) => c.direction === dir).sort((a, b) => b.total - a.total)
  const total = summary.reduce((s, c) => s + c.total, 0)

  return (
    <div className="grid" style={{ gap: 20 }}>
      <div className="page-head" style={{ marginBottom: 0 }}>
        <div>
          <h1>Операции и структура платежей</h1>
          <p>Структура расходов и поступлений по выписке с автоматической классификацией по назначению платежа.</p>
        </div>
      </div>

      <div className="grid-main">
        <section className="card">
          <div className="card-head">
            <div className="row" style={{ gap: 8, alignItems: 'center' }}>
              <h2>{dir === 'out' ? 'Структура расходов' : 'Структура поступлений'}</h2>
              <Hint>Сумма операций по категориям за период выписки. Нажмите на строку графика, чтобы отфильтровать список операций.</Hint>
            </div>
            <div className="seg">
              <button
                type="button"
                className={dir === 'out' ? 'on' : ''}
                onClick={() => {
                  setDir('out')
                  setCategory(null)
                }}
              >
                Расходы
              </button>
              <button
                type="button"
                className={dir === 'in' ? 'on' : ''}
                onClick={() => {
                  setDir('in')
                  setCategory(null)
                }}
              >
                Поступления
              </button>
            </div>
          </div>

          {cat.loading && <Loading height={260} />}
          {cat.error && <ErrorBox message={cat.error} onRetry={cat.reload} />}

          {summary.length > 0 && (
            <div style={{ height: Math.max(180, summary.length * 42) }}>
              <ResponsiveContainer>
                <BarChart
                  data={summary}
                  layout="vertical"
                  margin={{ left: 0, right: 75, top: 0, bottom: 0 }}
                  onClick={(e) => {
                    const p = (e as { activeLabel?: string })?.activeLabel
                    if (p) setCategory((c) => (c === p ? null : p))
                  }}
                >
                  <XAxis type="number" hide />
                  <YAxis
                    type="category"
                    dataKey="category"
                    width={170}
                    tick={{ fontSize: 13, fill: 'var(--text)' }}
                    tickLine={false}
                    axisLine={false}
                  />
                  <Tooltip
                    formatter={(v) => fmtRub(Number(v))}
                    contentStyle={{
                      background: 'var(--surface)',
                      borderColor: 'var(--border)',
                      borderRadius: 10,
                      boxShadow: 'var(--shadow-popover)',
                    }}
                  />
                  <Bar
                    dataKey="total"
                    name="Сумма"
                    radius={[0, 6, 6, 0]}
                    style={{ cursor: 'pointer' }}
                    label={{
                      position: 'right',
                      fontSize: 12,
                      fill: 'var(--text-2)',
                      formatter: (v: unknown) => `${fmtRubShort(Number(v))} · ${fmtPct(Number(v) / (total || 1))}`,
                    }}
                  >
                    {summary.map((c, i) => (
                      <Cell
                        key={c.category}
                        fill={PALETTE[i % PALETTE.length]}
                        fillOpacity={!category || category === c.category ? 1 : 0.3}
                      />
                    ))}
                  </Bar>
                </BarChart>
              </ResponsiveContainer>
            </div>
          )}

          {!cat.loading && !cat.error && summary.length === 0 && <Empty title="Операции не найдены" />}
        </section>

        <section className="card">
          <div className="card-head">
            <div className="row" style={{ gap: 8, alignItems: 'center' }}>
              <h2>Регулярные платежи</h2>
              <Hint>Платежи со стабильной суммой и периодичностью. Модель использует их для прогнозирования кассовых разрывов.</Hint>
            </div>
          </div>

          {rec.loading && <Loading height={260} />}
          {rec.error && <ErrorBox message={rec.error} onRetry={rec.reload} />}

          <div className="grid" style={{ gap: 0 }}>
            {[...(rec.data ?? [])]
              .sort((a, b) => a.next_date.localeCompare(b.next_date))
              .map((r) => (
                <div key={r.name} style={{ padding: '12px 0', borderBottom: '1px solid var(--border-light)' }}>
                  <div className="row" style={{ justifyContent: 'space-between', flexWrap: 'nowrap', alignItems: 'center' }}>
                    <span style={{ fontWeight: 600, color: 'var(--text)' }}>{r.name}</span>
                    <b className="num" style={{ whiteSpace: 'nowrap', color: r.direction === 'in' ? 'var(--ok-accent)' : 'var(--text)' }}>
                      {r.direction === 'in' ? '+' : '−'}{fmtRub(r.amount_avg)}
                    </b>
                  </div>
                  <div className="tiny" style={{ color: 'var(--text-3)', marginTop: 2 }}>
                    {periodText(r.period_days)} · следующий {fmtDay(r.next_date)} · уверенность {fmtPct(r.confidence)}
                  </div>
                </div>
              ))}
          </div>

          {!rec.loading && !rec.error && !rec.data?.length && (
            <Empty
              icon={
                <svg width="36" height="36" viewBox="0 0 24 24" fill="none" stroke="var(--text-3)" strokeWidth="1.5">
                  <path d="M21.5 2v6h-6M21.34 15.57a10 10 0 1 1-.57-8.38l5.67-5.67" />
                </svg>
              }
              title="Регулярных платежей не обнаружено"
            >
              Для детекции циклических платежей требуется выписка за 2–3 месяца.
            </Empty>
          )}
        </section>
      </div>

      <section className="card">
        <div className="card-head" style={{ flexWrap: 'wrap', gap: 12 }}>
          <div className="row" style={{ gap: 10, alignItems: 'center' }}>
            <h2 style={{ margin: 0 }}>Журнал операций</h2>
            {category && (
              <span className="badge b-neutral" style={{ display: 'inline-flex', alignItems: 'center', gap: 6 }}>
                {category}
                <button
                  onClick={() => setCategory(null)}
                  style={{ border: 0, background: 'none', cursor: 'pointer', padding: 0, color: 'inherit', fontWeight: 700 }}
                  aria-label="Сбросить фильтр"
                >
                  ✕
                </button>
              </span>
            )}
          </div>
          <div style={{ position: 'relative', width: 320 }}>
            <input
              className="input"
              placeholder="Поиск: контрагент, назначение, ИНН"
              value={q}
              onChange={(e) => {
                setQ(e.target.value)
                setLimit(PAGE)
              }}
              style={{ width: '100%', paddingLeft: 34 }}
            />
            <svg
              width="15"
              height="15"
              viewBox="0 0 24 24"
              fill="none"
              stroke="var(--text-3)"
              strokeWidth="2"
              strokeLinecap="round"
              strokeLinejoin="round"
              style={{ position: 'absolute', left: 11, top: '50%', transform: 'translateY(-50%)' }}
            >
              <circle cx="11" cy="11" r="8" />
              <line x1="21" y1="21" x2="16.65" y2="16.65" />
            </svg>
          </div>
        </div>

        {txs.length === 0 && !cat.loading && (
          <Empty
            icon={
              <svg width="36" height="36" viewBox="0 0 24 24" fill="none" stroke="var(--text-3)" strokeWidth="1.5">
                <circle cx="11" cy="11" r="8" />
                <line x1="21" y1="21" x2="16.65" y2="16.65" />
              </svg>
            }
            title="Операции не найдены"
          >
            Попробуйте изменить поисковый запрос или сбросить фильтр по категории.
          </Empty>
        )}

        {txs.length > 0 && (
          <div className="table-wrap">
            <table className="table table-stack">
              <thead>
                <tr>
                  <th>Дата</th>
                  <th>Контрагент и назначение платежа</th>
                  <th>Категория</th>
                  <th className="r">Сумма</th>
                  <th className="r">Остаток на конец дня</th>
                </tr>
              </thead>
              <tbody>
                {txs.slice(0, limit).map((t, i) => (
                  <tr key={i}>
                    <td className="num" style={{ whiteSpace: 'nowrap', fontWeight: 500 }}>
                      {fmtDayShort(t.date)}
                    </td>
                    <td>
                      <div style={{ fontWeight: 500, color: 'var(--text)' }}>
                        {t.counterparty_name || <span className="muted">Контрагент не указан</span>}
                      </div>
                      <div className="tiny" style={{ color: 'var(--text-3)', marginTop: 2 }}>
                        {t.purpose || 'Без назначения'}
                      </div>
                    </td>
                    <td>
                      <span className="badge b-neutral">{t.category ?? '—'}</span>
                      {t.category_confidence != null && t.category_confidence < 0.7 && (
                        <div className="tiny" style={{ color: 'var(--warning)', marginTop: 2 }}>
                          низкая уверенность
                        </div>
                      )}
                    </td>
                    <td
                      className="r num"
                      style={{
                        whiteSpace: 'nowrap',
                        fontWeight: 600,
                        color: t.direction === 'in' ? 'var(--ok-accent)' : 'var(--text)',
                      }}
                    >
                      {t.direction === 'in' ? '+' : '−'}{fmtRub(t.amount, true)}
                    </td>
                    <td
                      className="r num muted"
                      style={{
                        whiteSpace: 'nowrap',
                        color: (t.balance_eod ?? 0) < 0 ? 'var(--danger)' : undefined,
                        fontWeight: (t.balance_eod ?? 0) < 0 ? 600 : 400,
                      }}
                    >
                      {t.balance_eod != null ? fmtRub(t.balance_eod) : '—'}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}

        {txs.length > limit && (
          <div style={{ textAlign: 'center', marginTop: 16 }}>
            <button className="btn btn-ghost" onClick={() => setLimit((l) => l + PAGE)}>
              Показать еще ({txs.length - limit})
            </button>
          </div>
        )}
      </section>
    </div>
  )
}
