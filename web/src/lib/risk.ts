import type { DailyPoint, Risk } from '../types'
import { fmtRub, parseDate } from './format'

export type RiskKind = 'gap' | 'below_comfort'

/** Вид риска: если ядро не прислало kind — считаем кассовым разрывом (как было в исходном контракте) */
export function riskKind(r: Risk): RiskKind {
  return r.kind ?? 'gap'
}

/**
 * Сколько не хватит при ожидаемом ходе событий: самый низкий ожидаемый остаток ниже нуля
 * в эпизоде риска (дата риска и 10 дней после). 0 — если ожидаемый остаток не уходит в минус.
 */
export function expectedShortfall(r: Risk, daily: DailyPoint[]): number {
  const from = parseDate(r.date).getTime()
  const to = from + 10 * 86_400_000
  const ep = daily.filter((d) => { const t = parseDate(d.date).getTime(); return t >= from && t <= to })
  const min = Math.min(0, ...ep.map((d) => d.balance_p50))
  return Math.round(-min / 1000) * 1000
}

/** Главный риск: сначала разрывы, потом самые серьёзные, потом самые ранние */
export function mainRisk(risks: Risk[]): Risk | undefined {
  const sev = { high: 0, medium: 1, low: 2 }
  const kind = { gap: 0, below_comfort: 1 }
  return [...risks].sort((a, b) =>
    kind[riskKind(a)] - kind[riskKind(b)] || sev[a.severity] - sev[b.severity] || a.date.localeCompare(b.date))[0]
}

/** Короткое описание суммы риска простыми словами */
export function shortfallText(r: Risk, daily: DailyPoint[], comfort?: number): { main: string; sub?: string } {
  if (riskKind(r) === 'below_comfort') {
    return {
      main: comfort ? `меньше комфортного минимума ${fmtRub(comfort)}` : 'меньше комфортного запаса',
      sub: `Платежи пройдут, но запаса почти не останется. Чтобы его сохранить, может понадобиться до ${fmtRub(r.shortfall_amount)}.`,
    }
  }
  const exp = expectedShortfall(r, daily)
  if (exp > 0) {
    return {
      main: fmtRub(exp),
      sub: r.shortfall_amount > exp * 1.1 ? `Если поступления задержатся — до ${fmtRub(r.shortfall_amount)}.` : undefined,
    }
  }
  return {
    main: `до ${fmtRub(r.shortfall_amount)}`,
    sub: 'Обычно денег хватает — нехватка возможна, если поступления задержатся или окажутся ниже обычного.',
  }
}
