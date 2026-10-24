import {
  Area, CartesianGrid, ComposedChart, Line, ReferenceArea, ReferenceDot, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis,
} from 'recharts'
import type { CashEvent, DailyPoint, EventType, Risk } from '../types'
import { fmtDayShort, fmtDayWeek, fmtRub, fmtRubShort } from '../lib/format'

export const EVENT_SHORT: Record<EventType, string> = {
  payroll: 'ФОТ',
  tax: 'Налог',
  loan: 'Кредит',
  contract: 'Договор',
  invoice: 'Счёт',
  manual: 'Платёж',
}

export const EVENT_ICON: Record<EventType, string> = EVENT_SHORT

export const EVENT_LABEL: Record<EventType, string> = {
  payroll: 'Зарплата',
  tax: 'Налоги',
  loan: 'Кредит',
  contract: 'Договор',
  invoice: 'Счёт',
  manual: 'Вручную',
}

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

function niceStep(raw: number): number {
  const p = 10 ** Math.floor(Math.log10(Math.max(raw, 1)))
  const m = raw / p
  return (m <= 1 ? 1 : m <= 2 ? 2 : m <= 2.5 ? 2.5 : m <= 5 ? 5 : 10) * p
}

export function BalanceChart({ base, compare, events = [], risks = [], start, comfort, height = 340 }: Props) {
  const byId = new Map(events.map((e) => [e.id, e]))
  const cmp = new Map(compare?.daily.map((d) => [d.date, d]))
  const rows: Row[] = []

  if (start) {
    rows.push({
      date: start.date,
      p50: start.balance,
      band: [start.balance, start.balance],
      evs: [],
      ...(compare ? { p50b: start.balance, bandb: [start.balance, start.balance] as [number, number] } : {}),
    })
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
              <stop offset="0%" stopColor="#d70f00" stopOpacity={0.04} />
              <stop offset="100%" stopColor="#d70f00" stopOpacity={0.14} />
            </linearGradient>
          </defs>
          <CartesianGrid stroke="#eaecf1" vertical={false} />
          <ReferenceArea y1={yMin} y2={0} fill="url(#belowZero)" ifOverflow="hidden" />
          {gaps.map(([a, b]) => (
            <ReferenceArea key={a} x1={a} x2={b} fill="#d70f00" fillOpacity={0.08} stroke="#d70f00" strokeOpacity={0.3} strokeDasharray="3 3" />
          ))}
          <XAxis dataKey="date" tickFormatter={fmtDayShort} tick={{ fontSize: 12, fill: '#8b8b8f' }} tickLine={false} axisLine={{ stroke: '#e2e4e9' }} minTickGap={18} />
          <YAxis domain={[yMin, yMax]} ticks={ticks} interval={0} tickFormatter={fmtRubShort} tick={{ fontSize: 12, fill: '#8b8b8f' }} tickLine={false} axisLine={false} width={76} />
          {comfort != null && comfort > 0 && comfort < yMax && (
            <ReferenceLine
              y={comfort}
              stroke="#d97706"
              strokeDasharray="6 4"
              strokeWidth={1.5}
              label={{ value: `комфортный минимум ${fmtRubShort(comfort)} ₽`, position: 'insideTopRight', fill: '#d97706', fontSize: 11, fontWeight: 500 }}
            />
          )}
          <ReferenceLine
            y={0}
            stroke="#d70f00"
            strokeWidth={1.5}
            strokeDasharray="4 4"
            label={{ value: '0 ₽ (Порог разрыва)', position: 'insideBottomLeft', fill: '#d70f00', fontSize: 11, fontWeight: 500 }}
          />

          {markers.map(({ date, e }) => (
            <ReferenceLine
              key={e.id}
              x={date}
              stroke={e.direction === 'in' ? '#50b848' : '#8b8b8f'}
              strokeDasharray="2 4"
              label={{
                value: EVENT_SHORT[e.type] ?? 'Платёж',
                position: 'top',
                fontSize: 10,
                fill: e.direction === 'in' ? '#398233' : '#555558',
                fontWeight: 600,
              }}
            />
          ))}

          <Area dataKey="band" stroke="none" fill={base.color} fillOpacity={compare ? 0.08 : 0.14} isAnimationActive={false} name="Возможный диапазон" />
          {compare && <Area dataKey="bandb" stroke="none" fill={compare.color} fillOpacity={0.1} isAnimationActive={false} name="Диапазон (сценарий)" />}
          <Line
            dataKey="p50"
            stroke={base.color}
            strokeWidth={compare ? 2 : 2.75}
            dot={false}
            isAnimationActive={false}
            name={base.label}
            strokeDasharray={compare ? '6 4' : undefined}
          />
          {compare && (
            <Line dataKey="p50b" stroke={compare.color} strokeWidth={2.75} dot={false} isAnimationActive={false} name={compare.label} />
          )}

          {risks.map((r) => {
            const row = (compare ?? base).daily.find((d) => d.date === r.date)
            return row ? <ReferenceDot key={r.date} x={r.date} y={row.balance_p50} r={5} fill="#d70f00" stroke="#ffffff" strokeWidth={2} /> : null
          })}

          <Tooltip content={<ChartTip baseLabel={base.label} cmpLabel={compare?.label} />} />
        </ComposedChart>
      </ResponsiveContainer>
    </div>
  )
}

function ChartTip({ active, payload, baseLabel, cmpLabel }: { active?: boolean; payload?: { payload: Row }[]; baseLabel: string; cmpLabel?: string }) {
  if (!active || !payload?.length) return null
  const r = payload[0].payload
  const neg = (v?: number) => (v != null && v < 0 ? { color: 'var(--danger)' } : undefined)
  return (
    <div className="card" style={{ padding: '12px 14px', fontSize: 13, minWidth: 230, boxShadow: 'var(--shadow-popover)', border: '1px solid var(--border)' }}>
      <div style={{ fontWeight: 600, color: 'var(--text)', marginBottom: 6 }}>{fmtDayWeek(r.date)}</div>
      <div>
        <span style={{ color: 'var(--text-2)' }}>{cmpLabel ? baseLabel : 'Ожидаемый остаток'}: </span>
        <b className="num" style={neg(r.p50)}>{fmtRub(r.p50 ?? 0)}</b>
      </div>
      {r.band && r.band[0] !== r.band[1] && (
        <div className="tiny" style={{ color: 'var(--text-3)', marginTop: 2 }}>
          Диапазон: {fmtRub(r.band[0])} … {fmtRub(r.band[1])}
        </div>
      )}
      {cmpLabel && r.p50b != null && (
        <div style={{ marginTop: 4, paddingTop: 4, borderTop: '1px solid var(--border-light)' }}>
          <span style={{ color: 'var(--text-2)' }}>{cmpLabel}: </span>
          <b className="num" style={neg(r.p50b)}>{fmtRub(r.p50b)}</b>
        </div>
      )}
      {r.evs.length > 0 && (
        <div style={{ marginTop: 8, borderTop: '1px solid var(--border-light)', paddingTop: 6, display: 'grid', gap: 4 }}>
          {r.evs.map((e) => (
            <div key={e.id} style={{ fontSize: 12, display: 'flex', alignItems: 'center', gap: 6 }}>
              <span
                style={{
                  width: 6,
                  height: 6,
                  borderRadius: '50%',
                  background: e.direction === 'in' ? 'var(--ok-accent)' : 'var(--text-3)',
                  flexShrink: 0,
                }}
              />
              <span style={{ color: 'var(--text-2)' }}>{e.counterparty ?? EVENT_LABEL[e.type]}:</span>
              <b className="num" style={{ color: e.direction === 'in' ? 'var(--ok-accent)' : 'var(--text)', marginLeft: 'auto' }}>
                {e.direction === 'in' ? '+' : '−'}{fmtRub(e.amount)}
              </b>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

export function ChartLegend({ items }: { items: { color: string; label: string; dashed?: boolean; band?: boolean }[] }) {
  return (
    <div className="row small muted" style={{ gap: 16, marginTop: 12 }}>
      {items.map((i) => (
        <span key={i.label} className="row" style={{ gap: 6 }}>
          {i.band
            ? <span style={{ width: 16, height: 8, background: i.color, opacity: 0.25, borderRadius: 2 }} />
            : <span style={{ width: 16, height: 0, borderTop: `2.5px ${i.dashed ? 'dashed' : 'solid'} ${i.color}` }} />}
          <span style={{ color: 'var(--text-2)' }}>{i.label}</span>
        </span>
      ))}
      <span className="row" style={{ gap: 6 }}>
        <span style={{ width: 16, height: 8, background: '#d70f00', opacity: 0.2, borderRadius: 2 }} />
        <span style={{ color: 'var(--text-2)' }}>Зона дефицита средств</span>
      </span>
      <span className="tiny" style={{ marginLeft: 'auto', color: 'var(--text-3)', fontWeight: 500 }}>
        Маркеры: ФОТ · Налоги · Кредит · Договоры
      </span>
    </div>
  )
}
