import {
  Area, CartesianGrid, ComposedChart, Line, ReferenceArea, ReferenceDot, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis,
} from 'recharts'
import type { CashEvent, DailyPoint, EventType, Risk } from '../types'
import { fmtDayShort, fmtDayWeek, fmtRub, fmtRubShort } from '../lib/format'

export const EVENT_ICON: Record<EventType, string> = { payroll: '👥', tax: '🧾', loan: '🏦', contract: '📄', invoice: '📄', manual: '✍️' }
export const EVENT_LABEL: Record<EventType, string> = { payroll: 'Зарплата', tax: 'Налоги', loan: 'Кредит', contract: 'Договор', invoice: 'Счёт', manual: 'Вручную' }

interface Series {
  daily: DailyPoint[]
  label: string
  color: string
}

interface Props {
  base: Series
  compare?: Series
  events?: CashEvent[]
  risks?: Risk[]
  start?: { date: string; balance: number }
  comfort?: number
  height?: number
}

type Row = {
  date: string
  p50?: number
  band?: [number, number]
  p50b?: number
  bandb?: [number, number]
  evs: CashEvent[]
}

export function BalanceChart({ base, compare, events = [], risks = [], start, comfort, height = 340 }: Props) {
  const byId = new Map(events.map((e) => [e.id, e]))
  const cmp = new Map(compare?.daily.map((d) => [d.date, d]))
  const rows: Row[] = []
  if (start) {
    rows.push({ date: start.date, p50: start.balance, band: [start.balance, start.balance], evs: [],
      ...(compare ? { p50b: start.balance, bandb: [start.balance, start.balance] as [number, number] } : {}) })
  }
  for (const d of base.daily) {
    const ids = d.events ?? events.filter((e) => e.date === d.date && e.status !== 'paid').map((e) => e.id)
    const c = cmp.get(d.date)
    rows.push({
      date: d.date,
      p50: d.balance_p50,
      band: [d.balance_low, d.balance_high],
      p50b: c?.balance_p50,
      bandb: c ? [c.balance_low, c.balance_high] : undefined,
      evs: ids.map((id) => byId.get(id)).filter((e): e is CashEvent => !!e),
    })
  }

  const all = rows.flatMap((r) => [r.band?.[0], r.band?.[1], r.bandb?.[0], r.bandb?.[1]]).filter((v): v is number => v != null)
  const minY = Math.min(0, ...all)
  const maxY = Math.max(...all, 0)
  const step = niceStep((maxY - minY) / 5)
  const yMin = Math.floor(minY / step) * step
  const yMax = Math.ceil(maxY / step) * step
  const ticks = Array.from({ length: Math.round((yMax - yMin) / step) + 1 }, (_, i) => yMin + i * step)

  const gapSeries = compare ?? base
  const gaps: [string, string][] = []
  let open: string | null = null
  let last = ''
  for (const d of gapSeries.daily) {
    if (d.balance_p50 < 0 && !open) open = d.date
    if (d.balance_p50 >= 0 && open) { gaps.push([open, last]); open = null }
    last = d.date
  }
  if (open) gaps.push([open, last])

  const big = Math.max(50_000, (yMax - yMin) * 0.05)
  const markers = rows.flatMap((r) => r.evs.filter((e) => e.amount >= big).map((e) => ({ date: r.date, e })))

  return (
    <div style={{ width: '100%', height }}>
      <ResponsiveContainer>
        <ComposedChart data={rows} margin={{ top: 28, right: 12, bottom: 0, left: 0 }}>
          <defs>
            <linearGradient id="belowZero" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor="#d23b3b" stopOpacity={0.05} />
              <stop offset="100%" stopColor="#d23b3b" stopOpacity={0.16} />
            </linearGradient>
          </defs>
          <CartesianGrid stroke="#e8ede5" vertical={false} />
          <ReferenceArea y1={yMin} y2={0} fill="url(#belowZero)" ifOverflow="hidden" />
          {gaps.map(([a, b]) => (
            <ReferenceArea key={a} x1={a} x2={b} fill="#d23b3b" fillOpacity={0.1} stroke="#d23b3b" strokeOpacity={0.25} strokeDasharray="3 3" />
          ))}
          <XAxis dataKey="date" tickFormatter={fmtDayShort} tick={{ fontSize: 12, fill: '#7a8a80' }} tickLine={false} axisLine={{ stroke: '#dfe6da' }} minTickGap={18} />
          <YAxis domain={[yMin, yMax]} ticks={ticks} interval={0} tickFormatter={fmtRubShort} tick={{ fontSize: 12, fill: '#7a8a80' }} tickLine={false} axisLine={false} width={76} />
          {comfort != null && comfort > 0 && comfort < yMax && (
            <ReferenceLine y={comfort} stroke="#d98a00" strokeDasharray="6 4" strokeWidth={1.5}
              label={{ value: `комфортный минимум ${fmtRubShort(comfort)} ₽`, position: 'insideTopRight', fill: '#9a6200', fontSize: 11 }} />
          )}
          <ReferenceLine y={0} stroke="#d23b3b" strokeWidth={1.5} label={{ value: '0 ₽ — деньги закончились', position: 'insideBottomLeft', fill: '#d23b3b', fontSize: 11 }} />

          {markers.map(({ date, e }) => (
            <ReferenceLine key={e.id} x={date} stroke={e.direction === 'in' ? '#8dc63f' : '#9aa7a0'} strokeDasharray="2 4"
              label={{ value: EVENT_ICON[e.type], position: 'top', fontSize: 15 }} />
          ))}

          <Area dataKey="band" stroke="none" fill={base.color} fillOpacity={compare ? 0.1 : 0.16} isAnimationActive={false} name="Возможный диапазон" />
          {compare && <Area dataKey="bandb" stroke="none" fill={compare.color} fillOpacity={0.12} isAnimationActive={false} name="Диапазон (сценарий)" />}
          <Line dataKey="p50" stroke={base.color} strokeWidth={compare ? 2 : 3} dot={false} isAnimationActive={false} name={base.label}
            strokeDasharray={compare ? '6 4' : undefined} />
          {compare && <Line dataKey="p50b" stroke={compare.color} strokeWidth={3} dot={false} isAnimationActive={false} name={compare.label} />}

          {risks.map((r) => {
            const row = (compare ?? base).daily.find((d) => d.date === r.date)
            return row ? <ReferenceDot key={r.date} x={r.date} y={row.balance_p50} r={6} fill="#d23b3b" stroke="#fff" strokeWidth={2} /> : null
          })}

          <Tooltip content={<ChartTip baseLabel={base.label} cmpLabel={compare?.label} />} />
        </ComposedChart>
      </ResponsiveContainer>
    </div>
  )
}

function niceStep(raw: number): number {
  const p = 10 ** Math.floor(Math.log10(Math.max(raw, 1)))
  const m = raw / p
  return (m <= 1 ? 1 : m <= 2 ? 2 : m <= 2.5 ? 2.5 : m <= 5 ? 5 : 10) * p
}

function ChartTip({ active, payload, baseLabel, cmpLabel }: { active?: boolean; payload?: { payload: Row }[]; baseLabel: string; cmpLabel?: string }) {
  if (!active || !payload?.length) return null
  const r = payload[0].payload
  const neg = (v?: number) => (v != null && v < 0 ? { color: 'var(--red)' } : undefined)
  return (
    <div className="card" style={{ padding: '10px 12px', fontSize: 13, minWidth: 220, boxShadow: '0 8px 24px rgba(0,0,0,.12)' }}>
      <b>{fmtDayWeek(r.date)}</b>
      <div style={{ marginTop: 6 }}>
        {cmpLabel ? baseLabel : 'Ожидаемый остаток'}: <b className="num" style={neg(r.p50)}>{fmtRub(r.p50 ?? 0)}</b>
      </div>
      {r.band && r.band[0] !== r.band[1] && (
        <div className="muted">Возможно: от {fmtRub(r.band[0])} до {fmtRub(r.band[1])}</div>
      )}
      {cmpLabel && r.p50b != null && (
        <div style={{ marginTop: 4 }}>{cmpLabel}: <b className="num" style={neg(r.p50b)}>{fmtRub(r.p50b)}</b></div>
      )}
      {r.evs.length > 0 && (
        <div style={{ marginTop: 8, borderTop: '1px solid var(--border)', paddingTop: 6, display: 'grid', gap: 3 }}>
          {r.evs.map((e) => (
            <div key={e.id}>
              {EVENT_ICON[e.type]} {e.counterparty ?? EVENT_LABEL[e.type]}:{' '}
              <b style={{ color: e.direction === 'in' ? 'var(--ok)' : 'var(--text)' }}>{e.direction === 'in' ? '+' : '−'}{fmtRub(e.amount)}</b>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

export function ChartLegend({ items }: { items: { color: string; label: string; dashed?: boolean; band?: boolean }[] }) {
  return (
    <div className="row small muted" style={{ gap: 16, marginTop: 8 }}>
      {items.map((i) => (
        <span key={i.label} className="row" style={{ gap: 6 }}>
          {i.band
            ? <span style={{ width: 18, height: 10, background: i.color, opacity: 0.25, borderRadius: 3 }} />
            : <span style={{ width: 18, height: 0, borderTop: `3px ${i.dashed ? 'dashed' : 'solid'} ${i.color}` }} />}
          {i.label}
        </span>
      ))}
      <span className="row" style={{ gap: 6 }}><span style={{ width: 18, height: 10, background: '#d23b3b', opacity: 0.2, borderRadius: 3 }} />Денег не хватает</span>
      <span>👥 зарплата · 🧾 налоги · 🏦 кредит · 📄 счета и договоры</span>
    </div>
  )
}
