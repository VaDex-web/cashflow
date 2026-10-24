import type {
  CashEvent, CategoriesResponse, DailyPoint, ForecastResult, IntegrationStatus, MetricsReport, NewCashEvent,
  PlanFact, Recurring, Risk, Scenario, ScenarioResult, SyncResponse, Transaction,
} from '../types'
import { fmtDay, fmtRub, parseDate, toISO } from '../lib/format'

const files = import.meta.glob('../../../docs/mock/*.json', { eager: true, import: 'default' })

function load<T>(name: string): T {
  const key = Object.keys(files).find((k) => k.endsWith(`/${name}`))
  if (!key) throw new Error(`Нет mock-файла ${name}`)
  return structuredClone(files[key]) as T
}

const delay = (ms = 300) => new Promise((r) => setTimeout(r, ms))

let events: CashEvent[] | null = null
const getEvents = () => (events ??= load<CashEvent[]>('events.json'))

let lowData = false
const syncedAt: Record<string, string> = {}

const KNOWN_COMPANIES: Record<string, { name: string; inn: string; industry: string }> = {
  C001: { name: 'ООО «Грузоперевозки-063»', inn: '0098524470', industry: 'Грузоперевозки' },
  C002: { name: 'ИП Предприниматель-156', inn: '003844671674', industry: 'Грузоперевозки' },
  C003: { name: 'ООО «Агро-191»', inn: '0040581584', industry: 'Сельское хозяйство' },
  C004: { name: 'ИП Предприниматель-744', inn: '007654124568', industry: 'Образовательный центр' },
  C005: { name: 'ООО «Агро-777»', inn: '0068128920', industry: 'Сельское хозяйство' },
  C006: { name: 'ООО «Оптторг-082»', inn: '0029733949', industry: 'Оптовая торговля' },
  C007: { name: 'ООО «Стройподряд-370»', inn: '0010720142', industry: 'Строительство' },
  C008: { name: 'ООО «Клиника-785»', inn: '0015905281', industry: 'Медицина' },
  C009: { name: 'ООО «Продукты-253»', inn: '0076352556', industry: 'Розница: продуктовый магазин' },
  C010: { name: 'ИП Предприниматель-943', inn: '009996999598', industry: 'Автосервис' },
  C011: { name: 'ООО «Оптторг-626»', inn: '0033380654', industry: 'Оптовая торговля' },
  C012: { name: 'ИП Предприниматель-665', inn: '008829440840', industry: 'Салон красоты' },
  C013: { name: 'ООО «Стройподряд-234»', inn: '0004372962', industry: 'Строительство' },
  C014: { name: 'ООО «Оптторг-422»', inn: '0019733026', industry: 'Оптовая торговля' },
  C015: { name: 'ИП Предприниматель-487', inn: '005764302668', industry: 'Салон красоты' },
  C016: { name: 'ООО «Кофейня-492»', inn: '0066910530', industry: 'Общепит' },
  C022: { name: 'ООО «Софт-Решения-224»', inn: '0076148720', industry: 'IT-услуги' },
  C042: { name: 'ООО «Торговый Дом-118»', inn: '0081239910', industry: 'Оптовая торговля' },
  'demo-yuzhny-vkus': { name: 'ООО «Южный Вкус»', inn: '6164099881', industry: 'Производство продуктов' },
}

interface DynamicCompany {
  id: string
  name: string
  forecast: ForecastResult
  categories: CategoriesResponse
  recurring: Recurring[]
  planFact: PlanFact
  events: CashEvent[]
}

const companyStorage: Record<string, DynamicCompany> = {}
let activeCompanyId = 'demo-yuzhny-vkus'
let activeCompanyName = 'ООО «Южный Вкус»'

async function readFullCsvText(file: File): Promise<string> {
  const buf = await file.arrayBuffer()
  try {
    const dec = new TextDecoder('utf-8', { fatal: true })
    return dec.decode(buf).replace(/^\ufeff/, '')
  } catch {
    try {
      const dec = new TextDecoder('windows-1251')
      return dec.decode(buf).replace(/^\ufeff/, '')
    } catch {
      return new TextDecoder('utf-8').decode(buf).replace(/^\ufeff/, '')
    }
  }
}

export const mockApi = {
  async login(username: string, password: string) {
    await delay()
    if (!username || !password) throw new Error('Введите логин и пароль')
    return load<{ access_token: string; token_type: string }>('login_response.json')
  },
  async demoLogin() {
    await delay()
    return load<{ access_token: string; token_type: string }>('login_response.json')
  },
  async me() {
    return {
      username: 'demo',
      company_id: activeCompanyId as string | null,
      company_name: activeCompanyName as string | null,
    }
  },
  async health() {
    return load<{ status: string }>('health.json')
  },

  async uploadStatement(file: File) {
    await delay(500)
    const text = await readFullCsvText(file)
    const lines = text.split(/\r?\n/).filter((l) => l.trim())
    if (lines.length < 2) throw new Error('В файле нет операций — проверьте, что это выписка в формате CSV')

    const sep = lines[0].includes(';') ? ';' : ','
    const headers = lines[0].split(sep).map((h) => h.trim().toLowerCase().replace(/^["'\ufeff]+|["']+$/g, ''))
    
    const colIdx = {
      company: headers.findIndex((h) => h.includes('company')),
      date: headers.findIndex((h) => h.includes('date') || h.includes('дата')),
      amount: headers.findIndex((h) => h.includes('amount') || h.includes('сумма')),
      dir: headers.findIndex((h) => h.includes('direction') || h.includes('направление') || h.includes('тип')),
      balance: headers.findIndex((h) => h.includes('balance') || h.includes('остаток')),
      name: headers.findIndex((h) => h.includes('name') || h.includes('контрагент') || h.includes('наименование')),
      inn: headers.findIndex((h) => h.includes('inn') || h.includes('инн')),
      purpose: headers.findIndex((h) => h.includes('purpose') || h.includes('назначение')),
    }

    let cid = ''
    const matchName = file.name.match(/(C\d{3})/i)
    if (matchName) cid = matchName[1].toUpperCase()

    let lastDate = '2026-09-30'
    let lastBalance = 0
    let totalIn = 0
    let totalOut = 0
    let opCount = 0
    const catBuckets: Record<string, { count: number; sum_in: number; sum_out: number }> = {}
    const counterpartySums: Record<string, { name: string; inn: string; count: number; sum_out: number; sum_in: number }> = {}
    const parsedTransactions: Transaction[] = []

    for (let i = 1; i < lines.length; i++) {
      const parts = lines[i].split(sep).map((p) => p.trim().replace(/^["']+|["']+$/g, ''))
      if (parts.length < 3) continue

      if (!cid && colIdx.company >= 0 && parts[colIdx.company]) {
        cid = parts[colIdx.company].trim()
      }

      const d = colIdx.date >= 0 ? parts[colIdx.date] : ''
      if (d && /^\d{4}-\d{2}-\d{2}/.test(d)) {
        lastDate = d.slice(0, 10)
      }

      const rawAmt = colIdx.amount >= 0 ? parseFloat(parts[colIdx.amount].replace(',', '.')) : 0
      const amt = isNaN(rawAmt) ? 0 : Math.abs(rawAmt)

      const dirRaw = colIdx.dir >= 0 ? parts[colIdx.dir].toLowerCase() : ''
      const isOut = dirRaw.includes('спис') || dirRaw.includes('расх') || dirRaw.includes('out') || dirRaw.includes('дебет') || (rawAmt < 0)

      let currentEod = lastBalance
      if (colIdx.balance >= 0 && parts[colIdx.balance]) {
        const b = parseFloat(parts[colIdx.balance].replace(',', '.'))
        if (!isNaN(b)) {
          lastBalance = b
          currentEod = b
        }
      }

      if (isOut) totalOut += amt
      else totalIn += amt
      opCount++

      const cpName = colIdx.name >= 0 ? parts[colIdx.name] : ''
      const cpInn = colIdx.inn >= 0 ? parts[colIdx.inn] : ''
      const purpose = colIdx.purpose >= 0 ? parts[colIdx.purpose] : ''

      if (cpName) {
        if (!counterpartySums[cpName]) {
          counterpartySums[cpName] = { name: cpName, inn: cpInn, count: 0, sum_out: 0, sum_in: 0 }
        }
        counterpartySums[cpName].count++
        if (isOut) counterpartySums[cpName].sum_out += amt
        else counterpartySums[cpName].sum_in += amt
      }

      let cat = 'other'
      const purpLow = purpose.toLowerCase()
      if (purpLow.includes('налог') || purpLow.includes('енп') || purpLow.includes('взнос')) cat = 'taxes'
      else if (purpLow.includes('зарплат') || purpLow.includes('оплат') && purpLow.includes('труд')) cat = 'payroll'
      else if (purpLow.includes('аренд')) cat = 'rent'
      else if (purpLow.includes('поставк') || purpLow.includes('товар') || purpLow.includes('закуп')) cat = 'suppliers'
      else if (!isOut) cat = 'revenue'

      if (!catBuckets[cat]) catBuckets[cat] = { count: 0, sum_in: 0, sum_out: 0 }
      catBuckets[cat].count++
      if (isOut) catBuckets[cat].sum_out += amt
      else catBuckets[cat].sum_in += amt

      if (parsedTransactions.length < 300) {
        parsedTransactions.push({
          date: d || lastDate,
          amount: amt,
          direction: isOut ? 'out' : 'in',
          counterparty_name: cpName || (isOut ? 'Поставщик / Контрагент' : 'Покупатель'),
          counterparty_inn: cpInn || '',
          purpose: purpose || (isOut ? 'Оплата по договору' : 'Оплата от покупателя за товары/услуги'),
          balance_eod: currentEod,
          category: cat,
          category_confidence: 0.95,
        })
      }
    }

    if (!cid) cid = file.name.replace(/\.[^/.]+$/, '').toUpperCase()
    if (!cid) cid = 'C001'

    const meta = KNOWN_COMPANIES[cid]
    const compName = meta ? meta.name : `Компания «${cid}»`
    activeCompanyId = cid
    activeCompanyName = compName

    parsedTransactions.sort((a, b) => b.date.localeCompare(a.date))

    const horizon = 30
    const startDate = parseDate(lastDate)
    const dailyPoints: DailyPoint[] = []

    const avgDailyIn = Math.max(10_000, totalIn / Math.max(30, opCount / 2))
    const avgDailyOut = Math.max(10_000, totalOut / Math.max(30, opCount / 2))
    const monthlyTurnover = totalIn > 0 ? (totalIn / Math.max(1, opCount)) * 30 : 2_500_000
    const comfortBalance = Math.round(Math.max(50_000, monthlyTurnover * 0.1) / 1000) * 1000

    let currentSimBalance = lastBalance
    let minBalanceP50 = currentSimBalance
    let firstGapDate: string | null = null
    let maxShortfall = 0

    for (let k = 1; k <= horizon; k++) {
      const curDt = new Date(startDate)
      curDt.setDate(curDt.getDate() + k)
      const curIso = toISO(curDt)
      const dayOfWeek = curDt.getDay()
      const dayOfMonth = curDt.getDate()

      const isWorkday = dayOfWeek >= 1 && dayOfWeek <= 5
      let dayIn = isWorkday ? avgDailyIn * (0.8 + 0.4 * Math.sin(k * 0.7)) : 0
      let dayOut = isWorkday ? avgDailyOut * (0.8 + 0.4 * Math.cos(k * 0.5)) : 0

      if (dayOfMonth === 28) {
        dayOut += Math.max(150_000, avgDailyIn * 5)
      }
      if (dayOfMonth === 10 || dayOfMonth === 25) {
        dayOut += Math.max(100_000, avgDailyIn * 3)
      }

      currentSimBalance += dayIn - dayOut
      if (currentSimBalance < minBalanceP50) minBalanceP50 = currentSimBalance

      const sigma = Math.max(50_000, avgDailyIn * 0.6) * Math.sqrt(k)
      const p50 = Math.round(currentSimBalance)
      const low = Math.round(currentSimBalance - 1.28 * sigma)
      const high = Math.round(currentSimBalance + 1.28 * sigma)

      if (p50 < 0 && !firstGapDate) firstGapDate = curIso
      if (p50 < 0 && -p50 > maxShortfall) maxShortfall = -p50

      dailyPoints.push({
        date: curIso,
        balance_p50: p50,
        balance_low: low,
        balance_high: high,
        events: [],
      })
    }

    const risks: Risk[] = []
    if (lastBalance < 0) {
      risks.push({
        date: dailyPoints[0]?.date ?? lastDate,
        shortfall_amount: Math.round(Math.abs(minBalanceP50)),
        probability: 1.0,
        severity: 'high',
        kind: 'gap',
        reason: `Остаток уже ниже нуля (${fmtRub(lastBalance)}): счёт в овердрафте. Лимит овердрафта исчерпан. По прогнозу на ${horizon} дней дефицит усилится.`,
        recommendations: [
          'Согласовать с банком реструктуризацию овердрафта.',
          'Перевести срочные поступления от дебиторов на счёт.',
          'Временно приостановить некритичные хозяйственные расходы.',
        ],
      })
    } else if (firstGapDate) {
      const prob = Math.min(0.96, Math.max(0.65, 0.75 + (maxShortfall / monthlyTurnover) * 0.2))
      risks.push({
        date: firstGapDate,
        shortfall_amount: Math.round(maxShortfall / 1000) * 1000,
        probability: Math.round(prob * 100) / 100,
        severity: 'high',
        kind: 'gap',
        reason: `К ${fmtDay(firstGapDate)} обязательные списания (налоги ЕНП 28-го числа, зарплата и оплата поставщикам) превысят поступления. Нехватка средств: около ${fmtRub(maxShortfall)}.`,
        recommendations: [
          `Оформить предодобренный овердрафт Банка Центр-Инвест на ${fmtRub(maxShortfall * 1.2)}.`,
          'Перенести расчеты с поставщиками на 5-7 дней.',
          'Запустить факторинг по крупным выставленным счетам.',
        ],
      })
    } else if (minBalanceP50 < comfortBalance) {
      risks.push({
        date: dailyPoints.find((d) => d.balance_p50 < comfortBalance)?.date ?? dailyPoints[10].date,
        shortfall_amount: Math.round((comfortBalance - minBalanceP50) / 1000) * 1000,
        probability: 0.45,
        severity: 'medium',
        kind: 'below_comfort',
        reason: `Остаток опускается ниже комфортного порога безопасности (${fmtRub(comfortBalance)}). Бизнес уязвим к задержкам оплат от клиентов.`,
        recommendations: [
          'Сформировать неснижаемый резервный остаток или открыть кредитную линию.',
          'Усилить контроль дебиторской задолженности.',
          'Подключить сервис автоматических напоминаний клиентам о платежах.',
        ],
      })
    }

    const recurringList: Recurring[] = []
    const sortedCps = Object.values(counterpartySums).sort((a, b) => b.sum_out - a.sum_out)
    for (const cp of sortedCps.slice(0, 5)) {
      if (cp.sum_out > 0) {
        recurringList.push({
          name: cp.name,
          direction: 'out',
          amount_avg: Math.round(cp.sum_out / Math.max(1, cp.count)),
          period_days: cp.count > 5 ? 7 : 30,
          next_date: toISO(new Date(startDate.getTime() + 7 * 864e5)),
          confidence: Math.min(0.95, 0.6 + cp.count * 0.05),
        })
      }
    }
    recurringList.push({
      name: 'Единый налоговый платёж (ЕНП)',
      direction: 'out',
      amount_avg: Math.round(avgDailyIn * 4),
      period_days: 30,
      next_date: toISO(new Date(startDate.getFullYear(), startDate.getMonth() + 1, 28)),
      confidence: 0.98,
    })

    const totalVolume = Math.max(1, totalIn + totalOut)
    const summaryItems = Object.entries(catBuckets).map(([key, v]) => ({
      category: key,
      direction: (v.sum_out > v.sum_in ? 'out' : 'in') as 'out' | 'in',
      total: Math.round(v.sum_out > v.sum_in ? v.sum_out : v.sum_in),
      count: v.count,
      share: Math.round(((v.sum_out + v.sum_in) / totalVolume) * 100) / 100,
    }))

    const planFactRows: PlanFact = [
      {
        period: toISO(new Date(startDate.getTime() - 28 * 864e5)),
        planned_in: Math.round(avgDailyIn * 6.8),
        actual_in: Math.round(avgDailyIn * 7.1),
        planned_out: Math.round(avgDailyOut * 6.5),
        actual_out: Math.round(avgDailyOut * 6.9),
        deviations: [],
      },
      {
        period: toISO(new Date(startDate.getTime() - 21 * 864e5)),
        planned_in: Math.round(avgDailyIn * 7.0),
        actual_in: Math.round(avgDailyIn * 6.6),
        planned_out: Math.round(avgDailyOut * 7.2),
        actual_out: Math.round(avgDailyOut * 7.0),
        deviations: [{ event_id: 'ev-1', text: 'Задержка поступления по счету от покупателя' }],
      },
      {
        period: toISO(new Date(startDate.getTime() - 14 * 864e5)),
        planned_in: Math.round(avgDailyIn * 6.9),
        actual_in: Math.round(avgDailyIn * 7.3),
        planned_out: Math.round(avgDailyOut * 7.0),
        actual_out: Math.round(avgDailyOut * 7.1),
        deviations: [],
      },
      {
        period: toISO(new Date(startDate.getTime() - 7 * 864e5)),
        planned_in: Math.round(avgDailyIn * 7.2),
        actual_in: Math.round(avgDailyIn * 7.0),
        planned_out: Math.round(avgDailyOut * 6.8),
        actual_out: Math.round(avgDailyOut * 7.4),
        deviations: [{ event_id: 'ev-2', text: 'Внеплановая закупка расходных материалов' }],
      },
    ]

    const dynamicEvents: CashEvent[] = [
      {
        id: 'ev-tax-next',
        date: toISO(new Date(startDate.getFullYear(), startDate.getMonth() + 1, 28)),
        amount: Math.round(avgDailyIn * 4),
        direction: 'out',
        type: 'tax',
        source: 'tax_calendar',
        status: 'expected',
        note: 'Единый налоговый платёж (ЕНП) за текущий период',
      },
      {
        id: 'ev-payroll-1',
        date: toISO(new Date(startDate.getFullYear(), startDate.getMonth() + 1, 10)),
        amount: Math.round(avgDailyIn * 3),
        direction: 'out',
        type: 'payroll',
        source: '1c',
        status: 'expected',
        note: 'Выплата заработной платы сотрудникам',
      },
      {
        id: 'ev-payroll-2',
        date: toISO(new Date(startDate.getFullYear(), startDate.getMonth() + 1, 25)),
        amount: Math.round(avgDailyIn * 2.5),
        direction: 'out',
        type: 'payroll',
        source: '1c',
        status: 'expected',
        note: 'Аванс по заработной плате',
      },
    ]

    const dynamicForecast: ForecastResult = {
      company_id: cid,
      generated_at: new Date().toISOString(),
      horizon_days: horizon,
      as_of: lastDate,
      current_balance: Math.round(lastBalance),
      comfort_balance: comfortBalance,
      daily: dailyPoints,
      risks,
      recurring: recurringList,
      sources_used: ['bank'],
      warnings: opCount < 50 ? ['Мало операций для долгосрочного прогноза — точность может быть снижена.'] : [],
    }

    companyStorage[cid] = {
      id: cid,
      name: compName,
      forecast: dynamicForecast,
      categories: { summary: summaryItems, transactions: parsedTransactions },
      recurring: recurringList,
      planFact: planFactRows,
      events: dynamicEvents,
    }

    return { company_id: cid }
  },

  async forecast(id: string, _horizon = 30): Promise<ForecastResult> {
    await delay()
    if (companyStorage[id]) {
      return applyEvents(companyStorage[id].forecast)
    }
    const fc = load<ForecastResult>(lowData ? 'forecast_low_data.json' : 'forecast.json')
    return applyEvents(fc)
  },

  async alerts(id: string): Promise<Risk[]> {
    await delay()
    return (await mockApi.forecast(id)).risks
  },

  async categories(id: string) {
    await delay()
    if (companyStorage[id]) {
      return companyStorage[id].categories
    }
    return load<CategoriesResponse>('categories.json')
  },

  async recurring(id: string) {
    await delay()
    if (companyStorage[id]) {
      return companyStorage[id].recurring
    }
    return load<Recurring[]>('recurring.json')
  },

  async events(id: string) {
    await delay()
    if (companyStorage[id]?.events) {
      return structuredClone(companyStorage[id].events)
    }
    return structuredClone(getEvents())
  },

  async addEvent(id: string, ev: NewCashEvent): Promise<CashEvent> {
    await delay()
    const created = { ...ev, id: `ev-manual-${Date.now()}` }
    if (companyStorage[id]) {
      companyStorage[id].events.push(created)
    } else {
      getEvents().push(created)
    }
    return created
  },

  async parseEvent(_id: string, _text: string): Promise<{ event: NewCashEvent; understood: string }> {
    await delay()
    throw new Error('Разбор фразы работает только с сервером — заполните поля ниже')
  },

  async runScenario(id: string, sc: Scenario): Promise<ScenarioResult> {
    await delay(600)
    const base = await mockApi.forecast(id)
    const evs = companyStorage[id]?.events ?? getEvents()
    const scenario = simulate(base, sc, evs)
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

  async planFact(id: string) {
    await delay()
    if (companyStorage[id]?.planFact) {
      return companyStorage[id].planFact
    }
    return load<PlanFact>('plan_fact.json')
  },

  async sync(_id: string, name: string): Promise<SyncResponse> {
    await delay(1200)
    syncedAt[name] = new Date().toISOString()
    return { ...load<SyncResponse>('sync_response.json'), name, synced_at: syncedAt[name] }
  },

  async integrations(_id: string): Promise<IntegrationStatus[]> {
    await delay()
    return ['bank', '1c', 'tax_calendar', 'registry', 'contracts', 'invoices'].map((name) => ({
      name, title: name, source: name, description: '', available: true, events: 0,
      last_sync: syncedAt[name] ?? null, message: '',
    }))
  },

  async uploadSource(id: string, name: string, _file: File): Promise<SyncResponse> {
    return mockApi.sync(id, name)
  },

  async addTransactions(id: string, _rows: Partial<Transaction>[]) {
    await delay()
    return mockApi.forecast(id)
  },

  async metrics(): Promise<MetricsReport> {
    return load<MetricsReport>('metrics.json')
  },
}

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
  const t = 1 / (1 + 0.2316419 * Math.abs(x))
  const y = 1 - 0.3989423 * Math.exp((-x * x) / 2) * t * (0.3193815 + t * (-0.3565638 + t * (1.781478 + t * (-1.821256 + t * 1.330274))))
  return x >= 0 ? y : 1 - y
}
