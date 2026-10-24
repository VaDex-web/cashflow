import { useMemo, useState, type ReactNode } from 'react'
import { api } from '../api/client'
import { BalanceChart, ChartLegend } from '../components/BalanceChart'
import { forecastToday } from '../components/RiskCard'
import { ErrorBox, Hint, Loading } from '../components/ui'
import { fmtDay, fmtRub, parseDate, toISO } from '../lib/format'
import { useSession } from '../lib/session'
import { useAsync } from '../lib/useAsync'
import type { ForecastResult, Scenario, ScenarioResult, ScenarioType } from '../types'
import { NoCompany } from './Dashboard'

interface ScenarioCardItem {
  type: ScenarioType
  title: string
  text: string
  icon: ReactNode
}

const CARDS: ScenarioCardItem[] = [
  {
    type: 'client_delay',
    title: 'Клиент заплатит позже',
    text: 'Крупный клиент задержит оплату на 2–4 недели',
    icon: (
      <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
        <circle cx="12" cy="12" r="10" />
        <polyline points="12 6 12 12 16 14" />
      </svg>
    ),
  },
  {
    type: 'revenue_drop',
    title: 'Выручка упадёт',
    text: 'Продажи окажутся ниже обычного на 10–30%',
    icon: (
      <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
        <polyline points="22 17 13.5 8.5 8.5 13.5 2 7" />
        <polyline points="16 17 22 17 22 11" />
      </svg>
    ),
  },
  {
    type: 'unplanned_expense',
    title: 'Внеплановый расход',
    text: 'Срочный ремонт, штраф, закупка оборудования',
    icon: (
      <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
        <rect width="20" height="14" x="2" y="5" rx="2" />
        <line x1="2" x2="22" y1="10" y2="10" />
      </svg>
    ),
  },
  {
    type: 'fixed_cost_growth',
    title: 'Вырастут расходы',
    text: 'Аренда, зарплата, кредиты подорожают',
    icon: (
      <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
        <path d="M6 22V4a2 2 0 0 1 2-2h8a2 2 0 0 1 2 2v18Z" />
        <path d="M6 12H4a2 2 0 0 0-2 2v8" />
        <path d="M18 9h2a2 2 0 0 1 2 2v11" />
      </svg>
    ),
  },
  {
    type: 'client_lost',
    title: 'Клиент уйдёт',
    text: 'Крупный клиент перестанет платить совсем',
    icon: (
      <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
        <path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2" />
        <circle cx="9" cy="7" r="4" />
        <line x1="17" x2="22" y1="8" y2="13" />
        <line x1="22" x2="17" y1="8" y2="13" />
      </svg>
    ),
  },
  {
    type: 'tax_increase',
    title: 'Вырастут налоги',
    text: 'Новая ставка: платежи в бюджет вырастут на N%',
    icon: (
      <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
        <rect x="3" y="4" width="18" height="18" rx="2" ry="2" />
        <line x1="16" y1="2" x2="16" y2="6" />
        <line x1="8" y1="2" x2="8" y2="6" />
        <line x1="3" y1="10" x2="21" y2="10" />
      </svg>
    ),
  },
]

function firstGap(f: ForecastResult) {
  const neg = f.daily.filter((d) => d.balance_p50 < 0)
  if (!neg.length) return null
  const to = parseDate(neg[0].date).getTime() + 10 * 86_400_000
  const win = neg.filter((d) => parseDate(d.date).getTime() <= to)
  return { date: neg[0].date, max: Math.round(-Math.min(...win.map((d) => d.balance_p50)) / 1000) * 1000 }
}

export function Scenarios() {
  const { companyId } = useSession()
  const events = useAsync(() => (companyId ? api.events(companyId) : Promise.resolve([])), [companyId])
  const recurring = useAsync(() => (companyId ? api.recurring(companyId) : Promise.resolve([])), [companyId])
  const [type, setType] = useState<ScenarioType>('client_delay')
  const [weeks, setWeeks] = useState(3)
  const [percent, setPercent] = useState(20)
  const [growth, setGrowth] = useState(10)
  const [tax, setTax] = useState(20)
  const [amount, setAmount] = useState(300_000)
  const [date, setDate] = useState('')
  const [client, setClient] = useState('')
  const [res, setRes] = useState<ScenarioResult | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const clients = useMemo(() => {
    const out: { value: string; label: string; amount: number }[] = []
    const seen = new Set<string>()
    for (const e of (events.data ?? []).filter((x) => x.direction === 'in' && x.status !== 'paid')) {
      out.push({ value: e.id, label: `${e.counterparty ?? e.note ?? e.id} — ${fmtRub(e.amount)}, ${fmtDay(e.date)}`, amount: e.amount })
      if (e.counterparty) seen.add(e.counterparty.toLowerCase())
    }
    for (const r of (recurring.data ?? []).filter((x) => x.direction === 'in')) {
      const name = recurringCounterparty(r.name)
      if (!name || seen.has(name.toLowerCase())) continue
      seen.add(name.toLowerCase())
      out.push({ value: name, label: `${name} — обычно ${fmtRub(r.amount_avg)}, следующий платёж ${fmtDay(r.next_date)}`, amount: r.amount_avg })
    }
    return out.sort((a, b) => b.amount - a.amount)
  }, [events.data, recurring.data])

  const clientId = client || clients[0]?.value || ''
  const regular = clients.filter((c) => !(events.data ?? []).some((e) => e.id === c.value))
  const lostOptions = regular.length ? regular : clients
  const lostId = lostOptions.some((c) => c.value === client) ? client : lostOptions[0]?.value || ''
  const defaultDate = useMemo(() => {
    const d = new Date()
    d.setDate(d.getDate() + 7)
    return toISO(d)
  }, [])

  if (!companyId) return <NoCompany />

  function build(): Scenario {
    switch (type) {
      case 'client_delay':
        return { type, params: { counterparty_or_event_id: clientId, weeks } }
      case 'revenue_drop':
        return { type, params: { percent } }
      case 'unplanned_expense':
        return { type, params: { amount, date: date || defaultDate } }
      case 'fixed_cost_growth':
        return { type, params: { percent: growth } }
      case 'client_lost':
        return { type, params: { counterparty_or_event_id: lostId } }
      case 'tax_increase':
        return { type, params: { percent: tax } }
    }
  }

  async function run() {
    setBusy(true)
    setError(null)
    try {
      setRes(await api.runScenario(companyId!, build()))
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="grid" style={{ gap: 20 }}>
      <div className="page-head" style={{ marginBottom: 0 }}>
        <div>
          <h1>Что если…</h1>
          <p>Проверьте заранее устойчивость денежного потока к изменениям и форс-мажорам.</p>
        </div>
      </div>

      <div className="grid" style={{ gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))', gap: 12 }}>
        {CARDS.map((c) => {
          const active = type === c.type
          return (
            <button
              key={c.type}
              type="button"
              onClick={() => {
                setType(c.type)
                setRes(null)
              }}
              className="card"
              style={{
                textAlign: 'left',
                cursor: 'pointer',
                padding: '16px 18px',
                borderWidth: active ? 2 : 1,
                borderColor: active ? 'var(--primary)' : 'var(--border)',
                background: active ? 'var(--primary-65)' : 'var(--surface)',
                color: active ? 'var(--primary-active)' : 'var(--text)',
                boxShadow: active ? '0 4px 14px rgba(80, 184, 72, 0.15)' : 'var(--shadow)',
                transition: 'all 0.2s',
              }}
            >
              <div style={{ color: active ? 'var(--primary-active)' : 'var(--text-2)', marginBottom: 8 }}>
                {c.icon}
              </div>
              <h3 style={{ fontSize: 15, fontWeight: 650, color: 'inherit' }}>{c.title}</h3>
              <p className="small muted" style={{ marginTop: 4, color: active ? 'var(--text)' : 'var(--text-3)', fontSize: 13, lineHeight: 1.4 }}>
                {c.text}
              </p>
            </button>
          )
        })}
      </div>

      <section className="card" style={{ padding: '22px 24px' }}>
        <div className="row" style={{ gap: 20, alignItems: 'flex-end', flexWrap: 'wrap' }}>
          {type === 'client_delay' && (
            <>
              <label className="field" style={{ minWidth: 280, flex: 1 }}>
                <span>Какой платёж задержится</span>
                <select className="input" value={clientId} onChange={(e) => setClient(e.target.value)}>
                  {clients.length === 0 && <option value="">Нет ожидаемых поступлений от клиентов</option>}
                  {clients.map((c) => (
                    <option key={c.value} value={c.value}>
                      {c.label}
                    </option>
                  ))}
                </select>
              </label>
              <Slider label="На сколько недель" value={weeks} min={2} max={4} step={1} onChange={setWeeks} fmt={(v) => `${v} нед.`} />
            </>
          )}

          {type === 'revenue_drop' && (
            <Slider label="Насколько упадёт выручка" value={percent} min={10} max={30} step={5} onChange={setPercent} fmt={(v) => `−${v}%`} />
          )}

          {type === 'unplanned_expense' && (
            <>
              <label className="field">
                <span>Сумма, ₽</span>
                <input
                  className="input num"
                  type="number"
                  min={1000}
                  step={10000}
                  value={amount}
                  onChange={(e) => setAmount(Number(e.target.value))}
                  style={{ width: 180 }}
                />
              </label>
              <label className="field">
                <span>Когда</span>
                <input
                  className="input"
                  type="date"
                  value={date || defaultDate}
                  onChange={(e) => setDate(e.target.value)}
                />
              </label>
            </>
          )}

          {type === 'fixed_cost_growth' && (
            <Slider label="На сколько вырастут расходы" value={growth} min={5} max={30} step={5} onChange={setGrowth} fmt={(v) => `+${v}%`} />
          )}

          {type === 'client_lost' && (
            <label className="field" style={{ minWidth: 280, flex: 1 }}>
              <span>Какой клиент перестанет платить</span>
              <select className="input" value={lostId} onChange={(e) => setClient(e.target.value)}>
                {lostOptions.length === 0 && <option value="">Нет регулярных клиентов в выписке</option>}
                {lostOptions.map((c) => (
                  <option key={c.value} value={c.value}>
                    {c.label}
                  </option>
                ))}
              </select>
            </label>
          )}

          {type === 'tax_increase' && (
            <Slider label="На сколько вырастут налоги" value={tax} min={5} max={50} step={5} onChange={setTax} fmt={(v) => `+${v}%`} />
          )}

          <button
            type="button"
            className="btn btn-lime"
            onClick={run}
            disabled={busy || (type === 'client_delay' && !clientId) || (type === 'client_lost' && !lostId)}
            style={{ padding: '12px 24px', alignSelf: 'flex-end' }}
          >
            {busy ? 'Считаем…' : 'Показать результат'}
          </button>
        </div>
      </section>

      {error && <ErrorBox message={error} onRetry={run} />}
      {busy && !res && <Loading height={380} />}
      {res && <ScenarioView res={res} />}
    </div>
  )
}

function Slider({
  label,
  value,
  min,
  max,
  step,
  onChange,
  fmt,
}: {
  label: string
  value: number
  min: number
  max: number
  step: number
  onChange(v: number): void
  fmt(v: number): string
}) {
  return (
    <label className="field" style={{ minWidth: 240, flex: 1 }}>
      <span className="row" style={{ justifyContent: 'space-between' }}>
        <span>{label}</span>
        <b style={{ color: 'var(--primary-active)', fontSize: 16 }}>{fmt(value)}</b>
      </span>
      <input
        type="range"
        min={min}
        max={max}
        step={step}
        value={value}
        onChange={(e) => onChange(Number(e.target.value))}
        style={{ accentColor: 'var(--primary)' }}
      />
      <span className="row tiny" style={{ justifyContent: 'space-between', color: 'var(--text-3)' }}>
        <span>{fmt(min)}</span>
        <span>{fmt(max)}</span>
      </span>
    </label>
  )
}

function recurringCounterparty(name: string): string {
  const m = name.split(' — ')[1]
  return (m ?? '').replace(/\s*\(~?[^)]*\)\s*$/, '').trim()
}

function ScenarioView({ res }: { res: ScenarioResult }) {
  const b = firstGap(res.base)
  const s = firstGap(res.scenario)
  const today = forecastToday(res.base)
  const start = res.base.current_balance

  let tone: 'bad' | 'same' | 'ok' = 'same'
  let text: string
  if (!s) {
    tone = 'ok'
    text = b ? 'В этом случае разрыва не будет — остаток не уходит ниже нуля.' : 'Даже в этом случае денег хватит: остаток не уходит ниже нуля.'
  } else if (!b) {
    tone = 'bad'
    text = `Появится разрыв: ${fmtDay(s.date)} не хватит ${fmtRub(s.max)}. В обычном прогнозе ожидаемый остаток не уходит ниже нуля.`
  } else {
    const earlier = parseDate(s.date) < parseDate(b.date)
    const later = parseDate(s.date) > parseDate(b.date)
    const worse = s.max > b.max * 1.03 + 10_000
    const better = s.max < b.max * 0.97 - 10_000
    tone = earlier || worse ? 'bad' : better || later ? 'ok' : 'same'
    const amounts = worse || better ? `не хватит ${fmtRub(s.max)} вместо ${fmtRub(b.max)}` : `не хватит примерно столько же — ${fmtRub(s.max)}`
    text = earlier || later
      ? `Разрыв сдвинется с ${fmtDay(b.date)} на ${fmtDay(s.date)}, ${amounts}.`
      : worse
      ? `Разрыв останется ${fmtDay(s.date)}, но не хватит уже ${fmtRub(s.max)} вместо ${fmtRub(b.max)}.`
      : `Разрыв останется ${fmtDay(s.date)}, ${amounts}.`
  }
  const color = tone === 'bad' ? 'var(--danger)' : tone === 'ok' ? 'var(--ok-accent)' : 'var(--warning)'
  const bg = tone === 'bad' ? 'var(--danger-bg)' : tone === 'ok' ? 'var(--ok-bg)' : 'var(--warning-bg)'
  const border = tone === 'bad' ? 'var(--danger-border)' : tone === 'ok' ? 'var(--ok-border)' : 'var(--warning-border)'

  return (
    <section className="card">
      <div
        style={{
          background: bg,
          border: `1px solid ${border}`,
          borderRadius: 'var(--radius-md)',
          padding: '16px 20px',
          marginBottom: 20,
        }}
      >
        <div className="small" style={{ color, fontWeight: 700, textTransform: 'uppercase', letterSpacing: '0.04em' }}>
          Результат моделирования
        </div>
        <h2 style={{ fontSize: 20, marginTop: 4, color: 'var(--text)' }}>{text}</h2>
      </div>

      <div className="row" style={{ gap: 8, marginBottom: 8 }}>
        <h2>Сравнение базового прогноза и «Что если»</h2>
        <Hint>
          Пунктир — прогноз, если всё пойдёт как обычно. Сплошная линия — тот же прогноз с учётом выбранного сценария.
        </Hint>
      </div>

      <BalanceChart
        base={{ daily: res.base.daily, label: 'Обычный прогноз', color: '#1e6091' }}
        compare={{ daily: res.scenario.daily, label: 'Если это случится', color: '#d70f00' }}
        risks={res.scenario.risks}
        start={start != null ? { date: today, balance: start } : undefined}
      />
      <ChartLegend
        items={[
          { color: '#1e6091', label: 'Обычный прогноз', dashed: true },
          { color: '#d70f00', label: 'Сценарий «Что если»' },
        ]}
      />

      {res.scenario.risks[0]?.recommendations.length > 0 && (
        <div style={{ marginTop: 20, paddingTop: 16, borderTop: '1px solid var(--border-light)' }}>
          <h3 style={{ fontSize: 15, marginBottom: 8 }}>Что можно сделать заранее:</h3>
          <ul className="small" style={{ margin: 0, paddingLeft: 18, display: 'grid', gap: 6, color: 'var(--text-2)' }}>
            {res.scenario.risks[0].recommendations.map((t) => (
              <li key={t}>{t}</li>
            ))}
          </ul>
        </div>
      )}
    </section>
  )
}
