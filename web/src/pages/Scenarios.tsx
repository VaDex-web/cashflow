import { useMemo, useState } from 'react'
import { api } from '../api/client'
import { BalanceChart, ChartLegend } from '../components/BalanceChart'
import { forecastToday } from '../components/RiskCard'
import { ErrorBox, Hint, Loading } from '../components/ui'
import { fmtDay, fmtRub, parseDate, toISO } from '../lib/format'
import { useSession } from '../lib/session'
import { useAsync } from '../lib/useAsync'
import type { ForecastResult, Scenario, ScenarioResult, ScenarioType } from '../types'
import { NoCompany } from './Dashboard'

const CARDS: { type: ScenarioType; icon: string; title: string; text: string }[] = [
  { type: 'client_delay', icon: '⏳', title: 'Клиент заплатит позже', text: 'Крупный клиент задержит оплату на 2–4 недели' },
  { type: 'revenue_drop', icon: '📉', title: 'Выручка упадёт', text: 'Продажи окажутся ниже обычного на 10–30%' },
  { type: 'unplanned_expense', icon: '🔧', title: 'Внеплановый расход', text: 'Срочный ремонт, штраф, закупка оборудования' },
  { type: 'fixed_cost_growth', icon: '🏢', title: 'Вырастут постоянные расходы', text: 'Аренда, зарплата, кредиты подорожают' },
]

function firstGap(f: ForecastResult) {
  const neg = f.daily.filter((d) => d.balance_p50 < 0)
  return neg.length ? { date: neg[0].date, max: -Math.min(...neg.map((d) => d.balance_p50)) } : null
}

export function Scenarios() {
  const { companyId } = useSession()
  const events = useAsync(() => (companyId ? api.events(companyId) : Promise.resolve([])), [companyId])
  const [type, setType] = useState<ScenarioType>('client_delay')
  const [weeks, setWeeks] = useState(3)
  const [percent, setPercent] = useState(20)
  const [growth, setGrowth] = useState(10)
  const [amount, setAmount] = useState(300_000)
  const [date, setDate] = useState('')
  const [client, setClient] = useState('')
  const [res, setRes] = useState<ScenarioResult | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const inflows = useMemo(
    () => (events.data ?? []).filter((e) => e.direction === 'in' && e.status !== 'paid').sort((a, b) => b.amount - a.amount),
    [events.data],
  )
  const clientId = client || inflows[0]?.id || ''
  const defaultDate = useMemo(() => { const d = new Date(); d.setDate(d.getDate() + 7); return toISO(d) }, [])

  if (!companyId) return <NoCompany />

  function build(): Scenario {
    switch (type) {
      case 'client_delay': return { type, params: { counterparty_or_event_id: clientId, weeks } }
      case 'revenue_drop': return { type, params: { percent } }
      case 'unplanned_expense': return { type, params: { amount, date: date || defaultDate } }
      case 'fixed_cost_growth': return { type, params: { percent: growth } }
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
    <div className="grid" style={{ gap: 18 }}>
      <div className="page-head" style={{ marginBottom: 0 }}>
        <div>
          <h1>Что если…</h1>
          <p>Проверьте заранее, что будет с деньгами, если что-то пойдёт не по плану.</p>
        </div>
      </div>

      <div className="grid" style={{ gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))', gap: 12 }}>
        {CARDS.map((c) => (
          <button key={c.type} onClick={() => { setType(c.type); setRes(null) }} className="card"
            style={{ textAlign: 'left', cursor: 'pointer', padding: 16, borderWidth: 2, borderColor: type === c.type ? 'var(--lime-600)' : 'var(--border)', background: type === c.type ? 'var(--lime-100)' : 'var(--surface)' }}>
            <div style={{ fontSize: 24 }}>{c.icon}</div>
            <h3 style={{ marginTop: 6 }}>{c.title}</h3>
            <p className="small muted" style={{ marginTop: 4 }}>{c.text}</p>
          </button>
        ))}
      </div>

      <section className="card">
        <div className="row" style={{ gap: 20, alignItems: 'flex-end' }}>
          {type === 'client_delay' && (
            <>
              <label className="field" style={{ minWidth: 280, flex: 1 }}>Какой платёж задержится
                <select className="input" value={clientId} onChange={(e) => setClient(e.target.value)}>
                  {inflows.length === 0 && <option value="">Нет ожидаемых поступлений</option>}
                  {inflows.map((e) => (
                    <option key={e.id} value={e.id}>{e.counterparty ?? e.note ?? e.id} — {fmtRub(e.amount)}, {fmtDay(e.date)}</option>
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
              <label className="field">Сумма, ₽
                <input className="input num" type="number" min={1000} step={10000} value={amount} onChange={(e) => setAmount(Number(e.target.value))} style={{ width: 180 }} />
              </label>
              <label className="field">Когда
                <input className="input" type="date" value={date || defaultDate} onChange={(e) => setDate(e.target.value)} />
              </label>
            </>
          )}
          {type === 'fixed_cost_growth' && (
            <Slider label="На сколько вырастут постоянные расходы" value={growth} min={5} max={30} step={5} onChange={setGrowth} fmt={(v) => `+${v}%`} />
          )}
          <span className="spacer" />
          <button className="btn btn-lime" onClick={run} disabled={busy || (type === 'client_delay' && !clientId)} style={{ padding: '12px 22px' }}>
            {busy ? 'Считаем…' : 'Показать'}
          </button>
        </div>
      </section>

      {error && <ErrorBox message={error} onRetry={run} />}
      {busy && !res && <Loading height={380} />}
      {res && <ScenarioView res={res} />}
    </div>
  )
}

function Slider({ label, value, min, max, step, onChange, fmt }: { label: string; value: number; min: number; max: number; step: number; onChange(v: number): void; fmt(v: number): string }) {
  return (
    <label className="field" style={{ minWidth: 240, flex: 1 }}>
      <span className="row" style={{ justifyContent: 'space-between' }}>{label} <b style={{ color: 'var(--green-800)', fontSize: 16 }}>{fmt(value)}</b></span>
      <input type="range" min={min} max={max} step={step} value={value} onChange={(e) => onChange(Number(e.target.value))} style={{ accentColor: '#6fa62a' }} />
      <span className="row tiny" style={{ justifyContent: 'space-between' }}><span>{fmt(min)}</span><span>{fmt(max)}</span></span>
    </label>
  )
}

function ScenarioView({ res }: { res: ScenarioResult }) {
  const b = firstGap(res.base)
  // Фраза считается по ожидаемому остатку — так же, как нарисован график (delta ядра может считаться
  // от комфортного минимума, и тогда числа во фразе и на графике разошлись бы)
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
    text = `Появится разрыв: ${fmtDay(s.date)} не хватит ${fmtRub(s.max)}. Сейчас денег хватает.`
  } else {
    const earlier = parseDate(s.date) < parseDate(b.date)
    tone = earlier || s.max > b.max + 10_000 ? 'bad' : 'same'
    text = earlier
      ? `Разрыв сдвинется с ${fmtDay(b.date)} на ${fmtDay(s.date)}, не хватит ${fmtRub(s.max)} вместо ${fmtRub(b.max)}.`
      : `Разрыв останется ${fmtDay(s.date)}, но не хватит уже ${fmtRub(s.max)} вместо ${fmtRub(b.max)}.`
  }
  const color = tone === 'bad' ? 'var(--red)' : tone === 'ok' ? 'var(--ok)' : 'var(--amber)'
  const bg = tone === 'bad' ? 'var(--red-bg)' : tone === 'ok' ? 'var(--ok-bg)' : 'var(--amber-bg)'

  return (
    <section className="card">
      <div style={{ background: bg, borderRadius: 12, padding: '14px 16px', marginBottom: 16 }}>
        <div className="small" style={{ color, fontWeight: 650 }}>РЕЗУЛЬТАТ</div>
        <h2 style={{ fontSize: 22, marginTop: 4 }}>{text}</h2>
      </div>
      <div className="row" style={{ gap: 8, marginBottom: 6 }}>
        <h3>Обычный прогноз и прогноз «что если»</h3>
        <Hint>Пунктир — прогноз, если всё пойдёт как обычно. Сплошная красная линия — тот же прогноз с учётом выбранного события.</Hint>
      </div>
      <BalanceChart
        base={{ daily: res.base.daily, label: 'Обычный прогноз', color: '#11553f' }}
        compare={{ daily: res.scenario.daily, label: 'Если это случится', color: '#d23b3b' }}
        risks={res.scenario.risks}
        start={start != null ? { date: today, balance: start } : undefined}
      />
      <ChartLegend items={[
        { color: '#11553f', label: 'Обычный прогноз', dashed: true },
        { color: '#d23b3b', label: 'Если это случится' },
      ]} />
      {res.scenario.risks[0]?.recommendations.length > 0 && (
        <div style={{ marginTop: 16 }}>
          <h3>Что можно сделать заранее</h3>
          <ol className="small" style={{ margin: '6px 0 0', paddingLeft: 18, display: 'grid', gap: 4 }}>
            {res.scenario.risks[0].recommendations.map((t) => <li key={t}>{t}</li>)}
          </ol>
        </div>
      )}
    </section>
  )
}
