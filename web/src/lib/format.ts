const rub = new Intl.NumberFormat('ru-RU', { style: 'currency', currency: 'RUB', maximumFractionDigits: 0 })
const num = new Intl.NumberFormat('ru-RU', { maximumFractionDigits: 0 })

/** 270 000 ₽ (округляем до тысяч для крупных сумм, чтобы не было «ложной точности») */
export function fmtRub(x: number, exact = false): string {
  const v = !exact && Math.abs(x) >= 10_000 ? Math.round(x / 1000) * 1000 : Math.round(x)
  return rub.format(v).replace(/ /g, ' ')
}

/** 1,2 млн ₽ / 270 тыс ₽ — для осей графика */
export function fmtRubShort(x: number): string {
  const a = Math.abs(x)
  if (a >= 1_000_000) return `${(x / 1_000_000).toLocaleString('ru-RU', { maximumFractionDigits: 1 })} млн`
  if (a >= 1_000) return `${num.format(Math.round(x / 1000))} тыс`
  return num.format(x)
}

export function fmtPct(p: number): string {
  return `${Math.round(p * 100)}%`
}

export function parseDate(s: string): Date {
  const [y, m, d] = s.slice(0, 10).split('-').map(Number)
  return new Date(y, m - 1, d)
}

export function toISO(d: Date): string {
  const p = (n: number) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}`
}

/** 17 ноября */
export function fmtDay(s: string): string {
  return parseDate(s).toLocaleDateString('ru-RU', { day: 'numeric', month: 'long' })
}

/** 17 ноября, пт */
export function fmtDayWeek(s: string): string {
  const d = parseDate(s)
  return `${d.toLocaleDateString('ru-RU', { day: 'numeric', month: 'long' })}, ${d.toLocaleDateString('ru-RU', { weekday: 'short' })}`
}

/** 17.11 — для оси */
export function fmtDayShort(s: string): string {
  return parseDate(s).toLocaleDateString('ru-RU', { day: '2-digit', month: '2-digit' })
}

export function fmtDateTime(s: string): string {
  return new Date(s).toLocaleString('ru-RU', { day: 'numeric', month: 'long', hour: '2-digit', minute: '2-digit' })
}

export function daysBetween(from: string, to: string): number {
  return Math.round((parseDate(to).getTime() - parseDate(from).getTime()) / 86_400_000)
}

/** «через 14 дней» */
export function inDays(n: number): string {
  if (n <= 0) return 'сегодня'
  if (n === 1) return 'завтра'
  return `через ${n} ${plural(n, 'день', 'дня', 'дней')}`
}

export function plural(n: number, one: string, few: string, many: string): string {
  const m10 = n % 10
  const m100 = n % 100
  if (m10 === 1 && m100 !== 11) return one
  if (m10 >= 2 && m10 <= 4 && (m100 < 12 || m100 > 14)) return few
  return many
}

export function todayISO(): string {
  return toISO(new Date())
}
