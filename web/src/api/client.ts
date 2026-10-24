import type {
  CashEvent, CategoriesResponse, ForecastResult, IntegrationName, IntegrationStatus, MetricsReport, NewCashEvent,
  PlanFact, Recurring, Risk, Scenario, ScenarioResult, SyncResponse, Transaction, UploadSourceName,
} from '../types'
import { mockApi } from './mock'

export const USE_MOCK = import.meta.env.VITE_USE_MOCK === 'true'
const BASE = (import.meta.env.VITE_API_URL ?? '') + '/api'

const TOKEN_KEY = 'cf_token'
export const auth = {
  get token() {
    try { return localStorage.getItem(TOKEN_KEY) } catch { return null }
  },
  set(token: string | null) {
    try { token ? localStorage.setItem(TOKEN_KEY, token) : localStorage.removeItem(TOKEN_KEY) } catch {}
  },
}

export class ApiError extends Error {
  status: number
  constructor(message: string, status: number) {
    super(message)
    this.status = status
  }
}

const STATUS_TEXT: Record<number, string> = {
  400: 'Сервер не понял запрос — проверьте введённые данные',
  401: 'Сессия истекла — войдите заново',
  403: 'Нет доступа к этой компании',
  404: 'Данные не найдены — возможно, выписка ещё не загружена',
  413: 'Файл слишком большой',
  422: 'Проверьте формат данных',
  500: 'Ошибка на сервере. Попробуйте ещё раз через минуту',
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers)
  if (auth.token) headers.set('Authorization', `Bearer ${auth.token}`)
  if (init.body && !(init.body instanceof FormData)) headers.set('Content-Type', 'application/json')
  let res: Response
  try {
    res = await fetch(BASE + path, { ...init, headers })
  } catch {
    throw new ApiError('Нет связи с сервером. Проверьте интернет или запущен ли API', 0)
  }
  if (!res.ok) {
    let detail = ''
    try {
      const body = await res.json()
      detail = typeof body.detail === 'string' ? body.detail : Array.isArray(body.detail) ? body.detail.map((d: { msg?: string }) => d.msg).join('; ') : ''
    } catch {}
    if (res.status === 401) auth.set(null)
    throw new ApiError(detail || STATUS_TEXT[res.status] || `Ошибка ${res.status}`, res.status)
  }
  return res.json() as Promise<T>
}

const json = (body: unknown): RequestInit => ({ method: 'POST', body: JSON.stringify(body) })

const coreMetrics = import.meta.glob('../../../core/reports/metrics.json', { eager: true, import: 'default' })

const realApi = {
  login: (username: string, password: string) => request<{ access_token: string; token_type: string }>('/auth/login', json({ username, password })),
  demoLogin: () => request<{ access_token: string; token_type: string }>('/auth/demo', { method: 'POST' }),
  health: () => request<{ status: string }>('/health'),
  me: () => request<{ username: string; company_id: string | null; company_name: string | null }>('/me'),
  uploadStatement: (file: File) => {
    const fd = new FormData()
    fd.append('file', file)
    return request<{ company_id: string }>('/companies', { method: 'POST', body: fd })
  },
  forecast: (id: string, horizon = 30) => request<ForecastResult>(`/companies/${id}/forecast?horizon=${horizon}`),
  alerts: (id: string) => request<Risk[]>(`/companies/${id}/alerts`),
  categories: (id: string) => request<CategoriesResponse>(`/companies/${id}/categories`),
  recurring: (id: string) => request<Recurring[]>(`/companies/${id}/recurring`),
  events: (id: string) => request<CashEvent[]>(`/companies/${id}/events`),
  addEvent: (id: string, ev: NewCashEvent) => request<CashEvent>(`/companies/${id}/events`, json(ev)),
  parseEvent: (id: string, text: string) => request<{ event: NewCashEvent; understood: string }>(`/companies/${id}/events/parse`, json({ text })),
  runScenario: (id: string, sc: Scenario) => request<ScenarioResult>(`/companies/${id}/scenarios/run`, json(sc)),
  planFact: (id: string) => request<PlanFact>(`/companies/${id}/plan-fact`),
  sync: (id: string, name: IntegrationName) => request<SyncResponse>(`/companies/${id}/integrations/${name}/sync`, { method: 'POST' }),
  integrations: (id: string) => request<IntegrationStatus[]>(`/companies/${id}/integrations`),
  uploadSource: (id: string, name: UploadSourceName, file: File) => {
    const fd = new FormData()
    fd.append('file', file)
    return request<SyncResponse>(`/companies/${id}/integrations/${name}/upload`, { method: 'POST', body: fd })
  },
  addTransactions: (id: string, rows: Partial<Transaction>[]) => request<ForecastResult>(`/companies/${id}/transactions`, json(rows)),
  metrics: async (): Promise<MetricsReport> => {
    if (!USE_MOCK) {
      const r = await request<MetricsReport>('/metrics').catch(() => null)
      if (r) return r
    }
    const v = Object.values(coreMetrics)[0] as MetricsReport | undefined
    return v ?? mockApi.metrics()
  },
}

export const api: typeof realApi = USE_MOCK
  ? ({ ...mockApi, metrics: realApi.metrics } as unknown as typeof realApi)
  : realApi
