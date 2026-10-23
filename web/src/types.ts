// Типы строго по docs/contract.md. Поля с пометкой [proposal] — предложения, ещё не согласованы,
// поэтому необязательные: интерфейс должен работать и без них.

export type Direction = 'in' | 'out'
export type Severity = 'low' | 'medium' | 'high'

export type EventType = 'contract' | 'invoice' | 'tax' | 'loan' | 'payroll' | 'manual'
export type EventSource = 'bank' | '1c' | 'tax_calendar' | 'manual' | 'open_registry'
export type EventStatus = 'expected' | 'paid' | 'overdue'

export interface CashEvent {
  id: string
  type: EventType
  direction: Direction
  amount: number
  date: string
  source: EventSource
  status: EventStatus
  counterparty?: string
  note?: string
}

export type NewCashEvent = Omit<CashEvent, 'id'>

export type Scenario =
  | { type: 'client_delay'; params: { counterparty_or_event_id: string; weeks: number } }
  | { type: 'revenue_drop'; params: { percent: number } }
  | { type: 'unplanned_expense'; params: { amount: number; date: string } }
  | { type: 'fixed_cost_growth'; params: { percent: number } }

export type ScenarioType = Scenario['type']

export interface DailyPoint {
  date: string
  balance_p50: number
  balance_low: number
  balance_high: number
  events?: string[] // [proposal]
}

export interface Risk {
  date: string
  shortfall_amount: number
  probability: number
  severity: Severity
  reason: string
  recommendations: string[]
}

export interface Recurring {
  name: string
  direction: Direction
  amount_avg: number
  period_days: number
  next_date: string
  confidence: number
}

export interface ForecastResult {
  company_id: string
  generated_at: string
  horizon_days: number
  daily: DailyPoint[]
  risks: Risk[]
  recurring: Recurring[]
  sources_used: string[]
  warnings?: string[] // [proposal]
  current_balance?: number // [proposal]
  as_of?: string // [proposal]
}

export interface ScenarioResult {
  base: ForecastResult
  scenario: ForecastResult
  delta: { first_gap_date: string | null; max_shortfall: number | null }
}

export interface PlanFactRow {
  period: string
  planned_in: number
  actual_in: number
  planned_out: number
  actual_out: number
  deviations: { event_id: string; text: string }[]
}
export type PlanFact = PlanFactRow[]

export interface Transaction {
  date: string
  amount: number
  direction: Direction
  counterparty_name: string
  counterparty_inn: string
  purpose: string
  balance_eod: number
  category?: string
  category_confidence?: number
}

// [proposal] ответ /categories
export interface CategorySummary {
  category: string
  direction: Direction
  total: number
  count: number
  share: number
}
export interface CategoriesResponse {
  summary: CategorySummary[]
  transactions: Transaction[]
}

export type IntegrationName = 'bank' | '1c' | 'tax_calendar' | 'registry'
export interface SyncResponse {
  name: string
  status: string
  events_added?: number
  synced_at?: string
}

// [proposal] core/reports/metrics.json
export interface ModelMetrics {
  name: string
  mae: number
  mape: number
  coverage_80: number
  gap_recall: number
  gap_precision: number
  is_selected: boolean
}
export interface MetricsReport {
  _note?: string
  generated_at: string
  dataset: string
  horizon_days: number
  models: ModelMetrics[]
  backtest: { date: string; actual: number; predicted: number; low: number; high: number }[]
}
