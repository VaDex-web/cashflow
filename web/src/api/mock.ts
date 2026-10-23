// Заглушка API: читает docs/mock/*.json и повторяет поведение эндпоинтов из docs/contract.md.
// Сценарии «что если» в мок-режиме пересчитываются приближённо прямо в браузере —
// только чтобы демо работало без бэкенда. Настоящий расчёт делает core/.

import type {
  CashEvent, CategoriesResponse, DailyPoint, ForecastResult, MetricsReport, NewCashEvent,
  PlanFact, Recurring, Risk, Scenario, ScenarioResult, SyncResponse, Transaction,
} from '../types'
import { fmtDay, fmtRub, parseDate, toISO } from '../lib/format'

const files = import.meta.glob('../../../docs/mock/*.json', { eager: true, import: 'default' })

function load<T>(name: string): T {
  const key = Object.keys(files).find((k) => k.endsWith(`/${name}`))
  if (!key) throw new Error(`Нет mock-файла ${name}`)
  return structuredClone(files[key]) as T
}

const delay = (ms = 350) => new Promise((r) => setTimeout(r, ms))

let events: CashEvent[] | null = null
const getEvents = () => (events ??= load<CashEvent[]>('events.json'))

let lowData = false

export const mockApi = {
  async login(username: string, password: string) {
    await delay()
    if (!username || !password) throw new Error('Введите логин и пароль')
    return load<{ access_token: string; token_type: string }>('login_response.json')
  },
  async me() {
    return { username: 'demo', company_id: null as string | null, company_name: null as string | null }
  },
  async health() {
    return load<{ status: string }>('health.json')
  },
  async uploadStatement(file: File) {
    await delay(900)
    const text = await file.text()
    const lines = text.split(/\r?\n/).filter((l) => l.trim())
    if (lines.length < 2) throw new Error('В файле нет операций — проверьте, что это выписка в формате CSV')
    // Грубая оценка периода, чтобы показать предупреждение «данных мало»
    const dates = text.match(/\d{4}-\d{2}-\d{2}/g) ?? []
    const uniq = [...new Set(dates)].sort()
    lowData = uniq.length > 0 && (parseDate(uniq.at(-1)!).getTime() - parseDate(uniq[0]).getTime()) / 864e5 < 60
    return load<{ company_id: string }>('company_created.json')
  },
  async forecast(_id: string, _horizon = 30): Promise<ForecastResult> {
    await delay()
    const fc = load<ForecastResult>(lowData ? 'forecast_low_data.json' : 'forecast.json')
    return applyEvents(fc)
  },
  async alerts(_id: string): Promise<Risk[]> {
    await delay()
    return (await mockApi.forecast(_id)).risks
  },
  async categories(_id: string) {
    await delay()
    return load<CategoriesResponse>('categories.json')
  },
  async recurring(_id: string) {
    await delay()
    return load<Recurring[]>('recurring.json')
  },
  async events(_id: string) {
    await delay()
    return structuredClone(getEvents())
  },
  async addEvent(_id: string, ev: NewCashEvent): Promise<CashEvent> {
    await delay()
    const created = { ...ev, id: `ev-manual-${Date.now()}` }
    getEvents().push(created)
    return created
  },
  async runScenario(id: string, sc: Scenario): Promise<ScenarioResult> {
    await delay(600)
    const base = await mockApi.forecast(id)
    const scenario = simulate(base, sc, getEvents())
    const gaps = scenario.daily.filter((d) => d.balance_p50 < 0)
    return {
      base,
      scenario,
      delta: {
        first_gap_date: gaps[0]?.date ?? null,
        max_shortfall: gaps.length ? Math.round(-Math.min(...gaps.map((d) => d.balance_p50)) / 1000) * 1000 : 0,
      },
    }
  },
  async planFact(_id: string) {
    await delay()
    return load<PlanFact>('plan_fact.json')
  },
  async sync(_id: string, name: string): Promise<SyncResponse> {
    await delay(1200)
    return { ...load<SyncResponse>('sync_response.json'), name }
  },
  async addTransactions(id: string, _rows: Partial<Transaction>[]) {
    await delay()
    return mockApi.forecast(id)
  },
  async metrics(): Promise<MetricsReport> {
    return load<MetricsReport>('metrics.json')
  },
}

/** Ручные события, добавленные в мок-сессии, сдвигают прогноз */
function applyEvents(fc: ForecastResult): ForecastResult {
  const base = new Set(load<CashEvent[]>('events.json').map((e) => e.id))
  const added = getEvents().filter((e) => !base.has(e.id) && e.status === 'expected')
  if (!added.length) return fc
  let daily = fc.daily
  for (const e of added) daily = shiftFrom(daily, e.date, e.direction === 'in' ? e.amount : -e.amount, e.id)
  return { ...fc, daily, risks: recomputeRisks(daily, fc.risks) }
}

function shiftFrom(daily: DailyPoint[], from: string, amount: number, evId?: string, until?: string): DailyPoint[] {
  return daily.map((d) => {
    if (d.date < from || (until && d.date >= until)) return d
    const events = evId && d.date === from ? [...(d.events ?? []), evId] : d.events
    return { ...d, balance_p50: d.balance_p50 + amount, balance_low: d.balance_low + amount, balance_high: d.balance_high + amount, events }
  })
}

function simulate(base: ForecastResult, sc: Scenario, evs: CashEvent[]): ForecastResult {
  let daily = base.daily
  const start = parseDate(daily[0].date)
  switch (sc.type) {
    case 'unplanned_expense':
      daily = shiftFrom(daily, sc.params.date, -sc.params.amount)
      break
    case 'client_delay': {
      const ev = evs.find((e) => e.id === sc.params.counterparty_or_event_id || e.counterparty === sc.params.counterparty_or_event_id)
      if (ev) {
        const until = new Date(parseDate(ev.date))
        until.setDate(until.getDate() + 7 * sc.params.weeks)
        daily = shiftFrom(daily, ev.date, -ev.amount, undefined, toISO(until))
      }
      break
    }
    case 'revenue_drop': {
      // ~58 тыс ₽ выручки в будний день + крупные поступления от клиентов
      const inflows = evs.filter((e) => e.direction === 'in' && e.status === 'expected')
      let cum = 0
      daily = daily.map((d) => {
        const wd = parseDate(d.date).getDay()
        if (wd >= 1 && wd <= 5) cum += 58_000
        if (wd === 6) cum += 23_000
        cum += inflows.filter((e) => e.date === d.date).reduce((s, e) => s + e.amount, 0)
        const loss = (cum * sc.params.percent) / 100
        return { ...d, balance_p50: d.balance_p50 - loss, balance_low: d.balance_low - loss * 1.1, balance_high: d.balance_high - loss * 0.9 }
      })
      break
    }
    case 'fixed_cost_growth': {
      const monthly = base.recurring.filter((r) => r.direction === 'out' && r.period_days >= 28).reduce((s, r) => s + r.amount_avg, 0)
      const perDay = (monthly * sc.params.percent) / 100 / 30
      daily = daily.map((d) => {
        const t = (parseDate(d.date).getTime() - start.getTime()) / 864e5 + 1
        const loss = perDay * t
        return { ...d, balance_p50: d.balance_p50 - loss, balance_low: d.balance_low - loss, balance_high: d.balance_high - loss }
      })
      break
    }
  }
  daily = daily.map((d) => ({ ...d, balance_p50: Math.round(d.balance_p50), balance_low: Math.round(d.balance_low), balance_high: Math.round(d.balance_high) }))
  return { ...base, daily, risks: recomputeRisks(daily, base.risks) }
}

/** Упрощённый пересчёт рисков: эпизоды, где нижняя граница уходит ниже нуля */
function recomputeRisks(daily: DailyPoint[], original: Risk[]): Risk[] {
  const out: Risk[] = []
  let ep: DailyPoint[] = []
  const flush = () => {
    if (!ep.length) return
    const worst = ep.reduce((a, b) => (b.balance_p50 < a.balance_p50 ? b : a))
    const spread = Math.max(1, (worst.balance_high - worst.balance_low) / 2.563)
    const prob = Math.round(phi(-worst.balance_p50 / spread) * 100) / 100
    const shortfall = Math.round((worst.balance_p50 < 0 ? -worst.balance_p50 : -worst.balance_low) / 1000) * 1000
    const near = original.find((r) => Math.abs(parseDate(r.date).getTime() - parseDate(worst.date).getTime()) < 7 * 864e5)
    out.push({
      date: worst.date,
      shortfall_amount: shortfall,
      probability: prob,
      severity: prob >= 0.6 ? 'high' : prob >= 0.3 ? 'medium' : 'low',
      reason: near?.reason ?? `К ${fmtDay(worst.date)} расходы обгонят поступления — может не хватить около ${fmtRub(shortfall)}.`,
      recommendations: near?.recommendations ?? ['Перенесите необязательные платежи на более поздний срок.', 'Напомните клиентам о неоплаченных счетах.'],
    })
    ep = []
  }
  for (const d of daily) {
    if (d.balance_low < 0) ep.push(d)
    else flush()
  }
  flush()
  return out
}

function phi(x: number): number {
  // аппроксимация функции нормального распределения
  const t = 1 / (1 + 0.2316419 * Math.abs(x))
  const y = 1 - 0.3989423 * Math.exp((-x * x) / 2) * t * (0.3193815 + t * (-0.3565638 + t * (1.781478 + t * (-1.821256 + t * 1.330274))))
  return x >= 0 ? y : 1 - y
}
