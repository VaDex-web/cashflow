import { Area, CartesianGrid, ComposedChart, Legend, Line, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { api } from '../api/client'
import { ErrorBox, Hint, Loading } from '../components/ui'
import { fmtDayShort, fmtPct, fmtRub, fmtRubShort } from '../lib/format'

const fmtPct1 = (p: number) => `${(p * 100).toFixed(1).replace('.', ',')}%`
import { useAsync } from '../lib/useAsync'

export function Quality() {
  const m = useAsync(() => api.metrics(), [])
  if (m.loading) return <Loading height={400} />
  if (m.error || !m.data) return <ErrorBox message={m.error ?? 'Нет метрик'} onRetry={m.reload} />
  const r = m.data
  const isMock = r.dataset === 'MOCK' || !!r._note
  const best = r.models.find((x) => x.is_selected) ?? r.models[0]
  const blank = (v: number, f: (n: number) => string) => (isMock && !v ? 'подставить' : f(v))
  const data = r.backtest.map((b) => ({ ...b, band: [b.low, b.high] as [number, number] }))

  return (
    <div className="grid" style={{ gap: 18 }}>
      <div className="page-head" style={{ marginBottom: 0 }}>
        <div>
          <h1>Качество прогноза</h1>
          <p>Как мы проверяли, что прогнозу можно доверять: строили прогноз «из прошлого» и сравнивали с тем, что случилось на самом деле.</p>
        </div>
      </div>

      {isMock && <div className="notice notice-warn"><span>🧪</span><span>Здесь пока тестовые цифры — реальные метрики появятся, когда ядро выгрузит <code>core/reports/metrics.json</code>.</span></div>}

      {best && (
        <div className="grid" style={{ gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))', gap: 12 }}>
          <Big label="Средняя ошибка остатка" value={blank(best.mae, fmtRub)} hint="MAE: на сколько рублей в среднем прогноз отличается от фактического остатка на счёте на горизонте прогноза." />
          <Big label="Ошибка в долях оборота" value={blank(best.mape, fmtPct1)} hint="MAE, % оборота: средняя ошибка прогноза остатка в процентах от месячного оборота (списаний за месяц) — так ошибки малых и крупных компаний сравнимы." />
          <Big label="Факт внутри диапазона" value={blank(best.coverage_80, fmtPct)} hint="Доля дней, когда фактический остаток попал в «возможный диапазон». Цель — около 80%." />
          <Big label="Находим разрывы" value={blank(best.gap_recall, fmtPct)} hint="Recall: доля разрывов (деньги кончились бы без пополнения владельцем), о которых модель предупредила заранее." />
          <Big label="Точность предупреждений" value={blank(best.gap_precision, fmtPct)} hint="Precision: доля предупреждений, после которых разрыв действительно случился." />
        </div>
      )}

      <section className="card">
        <div className="card-head">
          <div className="row" style={{ gap: 8 }}>
            <h2>Сравнение подходов</h2>
            <Hint>Горизонт {r.horizon_days} дней. Данные: {r.dataset}. Меньше ошибка — лучше; больше охват и поиск разрывов — лучше.</Hint>
          </div>
        </div>
        <div className="table-wrap">
          <table className="table num">
            <thead><tr><th>Модель</th><th className="r">MAE, ₽</th><th className="r">MAE, % оборота</th><th className="r">В диапазоне</th><th className="r">Находит разрывы</th><th className="r">Точность</th></tr></thead>
            <tbody>
              {r.models.map((x) => (
                <tr key={x.name} style={x.is_selected ? { background: 'var(--lime-100)', fontWeight: 650 } : undefined}>
                  <td>{x.name} {x.is_selected && <span className="badge b-low">выбрана</span>}</td>
                  <td className="r" style={{ whiteSpace: 'nowrap' }}>{blank(x.mae, fmtRub)}</td>
                  <td className="r">{blank(x.mape, fmtPct1)}</td>
                  <td className="r">{blank(x.coverage_80, fmtPct)}</td>
                  <td className="r">{blank(x.gap_recall, fmtPct)}</td>
                  <td className="r">{blank(x.gap_precision, fmtPct)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      {data.length > 0 && (
        <section className="card">
          <div className="card-head"><h2>Прогноз против факта (бэктест)</h2></div>
          <div style={{ height: 320 }}>
            <ResponsiveContainer>
              <ComposedChart data={data} margin={{ top: 8, right: 8, bottom: 0, left: 0 }}>
                <CartesianGrid stroke="#e8ede5" vertical={false} />
                <XAxis dataKey="date" tickFormatter={fmtDayShort} tick={{ fontSize: 12, fill: '#7a8a80' }} tickLine={false} minTickGap={20} />
                <YAxis tickFormatter={fmtRubShort} tick={{ fontSize: 12, fill: '#7a8a80' }} tickLine={false} axisLine={false} width={72} />
                <Tooltip formatter={(v) => (Array.isArray(v) ? `${fmtRub(v[0])} – ${fmtRub(v[1])}` : fmtRub(Number(v)))} labelFormatter={(l) => fmtDayShort(String(l))} />
                <Legend />
                <Area dataKey="band" name="Возможный диапазон" stroke="none" fill="#11553f" fillOpacity={0.14} isAnimationActive={false} />
                <Line dataKey="predicted" name="Прогноз" stroke="#11553f" strokeWidth={2} strokeDasharray="6 4" dot={false} isAnimationActive={false} />
                <Line dataKey="actual" name="Факт" stroke="#6fa62a" strokeWidth={3} dot={false} isAnimationActive={false} />
              </ComposedChart>
            </ResponsiveContainer>
          </div>
        </section>
      )}
    </div>
  )
}

function Big({ label, value, hint }: { label: string; value: string; hint: string }) {
  return (
    <div className="card" style={{ padding: 16 }}>
      <div className="row small muted" style={{ gap: 6, flexWrap: 'nowrap' }}><span>{label}</span><Hint>{hint}</Hint></div>
      <div className="num" style={{ fontSize: 28, fontWeight: 700, marginTop: 4, color: 'var(--green-800)' }}>{value}</div>
    </div>
  )
}
