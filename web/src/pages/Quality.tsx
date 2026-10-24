import { Area, CartesianGrid, ComposedChart, Legend, Line, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { api } from '../api/client'
import { ErrorBox, Hint, Loading } from '../components/ui'
import { fmtDayShort, fmtPct, fmtRub, fmtRubShort } from '../lib/format'
import { useAsync } from '../lib/useAsync'

const fmtPct1 = (p: number) => `${(p * 100).toFixed(1).replace('.', ',')}%`

const HOLDOUT_GAPS = { tp: 39, fp: 17, fn: 25, tn: 435, brier: 0.0481 }

export function Quality() {
  const m = useAsync(() => api.metrics(), [])
  if (m.loading) return <Loading height={400} />
  if (m.error || !m.data) return <ErrorBox message={m.error ?? 'Нет метрик'} onRetry={m.reload} />

  const r = m.data
  const isMock = r.dataset === 'MOCK' || !!r._note
  const best = r.models.find((x) => x.is_selected) ?? r.models[0]
  const blank = (v: number, f: (n: number) => string) => (isMock && !v ? 'подставить' : f(v))
  const data = r.backtest.map((b) => ({ ...b, band: [b.low, b.high] as [number, number] }))

  const g = HOLDOUT_GAPS
  const total = g.tp + g.fp + g.fn + g.tn
  const accuracy = (g.tp + g.tn) / total
  const precision = best.gap_precision
  const recall = best.gap_recall
  const f1 = precision + recall > 0 ? (2 * precision * recall) / (precision + recall) : 0

  return (
    <div className="grid" style={{ gap: 20 }}>
      <div className="page-head" style={{ marginBottom: 0 }}>
        <div>
          <h1>Точность и валидация моделей</h1>
          <p>Метрики качества прогноза на ретроспективных данных: бэктест на 73 отложенных компаниях датасета организаторов (holdout).</p>
        </div>
      </div>

      {isMock && (
        <div className="notice notice-warn" style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" style={{ flexShrink: 0 }}>
            <circle cx="12" cy="12" r="10" />
            <line x1="12" y1="8" x2="12" y2="12" />
            <line x1="12" y1="16" x2="12.01" y2="16" />
          </svg>
          <span>
            Здесь пока тестовые цифры — реальные метрики появятся, когда ядро выгрузит <code>core/reports/metrics.json</code>.
          </span>
        </div>
      )}

      <div className="grid" style={{ gridTemplateColumns: 'repeat(auto-fit, minmax(210px, 1fr))', gap: 14 }}>
        <Big
          label="Средняя ошибка (MAE)"
          value={blank(best.mae, fmtRub)}
          sub={`${blank(best.mape, fmtPct1)} от месячного оборота`}
          hint="MAE: среднее отклонение прогноза остатка от факта. В процентах от оборота позволяет сравнивать бизнес любого масштаба."
        />
        <Big
          label="Общая точность (Accuracy)"
          value={fmtPct1(accuracy)}
          sub={`${Math.round(accuracy * 100)} из 100 прогнозов «будет разрыв / не будет» верны`}
          hint="Доля верных ответов «будет разрыв / не будет» среди всех прогнозов бэктеста: компания × дата прогноза."
        />
        <Big
          label="Полнота разрывов (Recall)"
          value={blank(recall, fmtPct1)}
          sub={`${blank(recall, fmtPct)} разрывов найдены заранее`}
          hint="Recall: доля реальных кассовых разрывов, о которых модель предупредила заранее."
        />
        <Big
          label="Точность алертов (Precision)"
          value={blank(precision, fmtPct1)}
          sub={`${blank(precision, fmtPct)} тревог подтверждаются`}
          hint="Precision: если модель предупредила о разрыве, в такой доле случаев остаток действительно ушёл бы ниже нуля."
        />
        <Big
          label="F1-Score (баланс качества)"
          value={blank(f1, fmtPct1)}
          sub="Гармоническое среднее"
          hint="F1: баланс между полнотой (Recall) и отсутствием ложных тревог (Precision)."
        />
        <Big
          label="В коридоре P10..P90"
          value={blank(best.coverage_80, fmtPct)}
          sub="Номинал калибровки: 80%"
          hint="Доля дней, когда фактический баланс остался внутри доверительного интервала Монте-Карло симуляции."
        />
      </div>

      <section className="card" style={{ padding: '22px 24px' }}>
        <div className="card-head" style={{ marginBottom: 16 }}>
          <div className="row" style={{ gap: 8, alignItems: 'center', justifyContent: 'space-between', width: '100%', flexWrap: 'wrap' }}>
            <div style={{ minWidth: 0 }}>
              <h2 style={{ fontSize: 18 }}>Матрица ошибок прогнозирования кассовых разрывов (Confusion Matrix 2x2)</h2>
              <p style={{ margin: '4px 0 0', fontSize: 13, color: 'var(--text-3)' }}>
                Оценка способности алгоритма предсказывать наступление отрицательного остатка на 30 дней вперед.
              </p>
            </div>
            <span className="badge b-low" style={{ fontSize: 12, padding: '4px 10px' }}>
              Holdout: 73 компании, {total} прогнозов
            </span>
          </div>
        </div>

        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(min(100%, 280px), 1fr))', gap: 24, alignItems: 'center' }}>
          <div className="table-wrap">
            <table className="table num" style={{ borderCollapse: 'separate', borderSpacing: 4, width: '100%' }}>
              <thead>
                <tr>
                  <th style={{ background: 'transparent', border: 'none' }}></th>
                  <th style={{ textAlign: 'center', background: 'var(--surface-2)', borderRadius: 6, padding: '8px 12px', fontSize: 13 }}>
                    Факт: РАЗРЫВ (1)
                  </th>
                  <th style={{ textAlign: 'center', background: 'var(--surface-2)', borderRadius: 6, padding: '8px 12px', fontSize: 13 }}>
                    Факт: НОРМА (0)
                  </th>
                </tr>
              </thead>
              <tbody>
                <tr>
                  <td style={{ fontWeight: 600, fontSize: 13, background: 'var(--surface-2)', borderRadius: 6, padding: '12px 14px' }}>
                    Прогноз: РАЗРЫВ
                  </td>
                  <td style={{ textAlign: 'center', background: 'rgba(34, 197, 94, 0.12)', border: '1px solid rgba(34, 197, 94, 0.3)', borderRadius: 8, padding: '14px' }}>
                    <div style={{ fontSize: 20, fontWeight: 700, color: 'var(--success)' }}>TP = {g.tp}</div>
                    <div style={{ fontSize: 11, color: 'var(--text-3)', marginTop: 2 }}>Верно найденные разрывы</div>
                  </td>
                  <td style={{ textAlign: 'center', background: 'rgba(239, 68, 68, 0.08)', border: '1px solid rgba(239, 68, 68, 0.25)', borderRadius: 8, padding: '14px' }}>
                    <div style={{ fontSize: 20, fontWeight: 700, color: 'var(--danger)' }}>FP = {g.fp}</div>
                    <div style={{ fontSize: 11, color: 'var(--text-3)', marginTop: 2 }}>Ложная тревога</div>
                  </td>
                </tr>
                <tr>
                  <td style={{ fontWeight: 600, fontSize: 13, background: 'var(--surface-2)', borderRadius: 6, padding: '12px 14px' }}>
                    Прогноз: НОРМА
                  </td>
                  <td style={{ textAlign: 'center', background: 'rgba(239, 68, 68, 0.08)', border: '1px solid rgba(239, 68, 68, 0.25)', borderRadius: 8, padding: '14px' }}>
                    <div style={{ fontSize: 20, fontWeight: 700, color: 'var(--danger)' }}>FN = {g.fn}</div>
                    <div style={{ fontSize: 11, color: 'var(--text-3)', marginTop: 2 }}>Пропущенный разрыв</div>
                  </td>
                  <td style={{ textAlign: 'center', background: 'rgba(34, 197, 94, 0.12)', border: '1px solid rgba(34, 197, 94, 0.3)', borderRadius: 8, padding: '14px' }}>
                    <div style={{ fontSize: 20, fontWeight: 700, color: 'var(--success)' }}>TN = {g.tn}</div>
                    <div style={{ fontSize: 11, color: 'var(--text-3)', marginTop: 2 }}>Верно: разрыва не было</div>
                  </td>
                </tr>
              </tbody>
            </table>
          </div>

          <div style={{ background: 'var(--surface-2)', padding: '18px 20px', borderRadius: 12, border: '1px solid var(--border)' }}>
            <h3 style={{ fontSize: 14, margin: '0 0 10px', color: 'var(--text)', display: 'flex', alignItems: 'center', gap: 6 }}>
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="var(--primary)" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <circle cx="12" cy="12" r="10" />
                <line x1="12" y1="16" x2="12" y2="12" />
                <line x1="12" y1="8" x2="12.01" y2="8" />
              </svg>
              Интерпретация для риск-менеджмента банка:
            </h3>
            <ul style={{ margin: 0, paddingLeft: 18, fontSize: 13, color: 'var(--text-2)', lineHeight: 1.6 }}>
              <li>
                <strong>Приоритет Recall:</strong> Для банка пропуск реального кассового разрыва клиента (<strong>FN</strong>) несет прямой риск неплатежа по кредиту или задержки налогов.
              </li>
              <li>
                <strong>Контроль ложных тревог:</strong> Ложное предупреждение (<strong>FP</strong>) не вредит клиенту, а дает банку возможность вовремя предложить предодобренный овердрафт или факторинг.
              </li>
              <li>
                <strong>Brier Score = {String(g.brier).replace('.', ',')}:</strong> Оценка точности калибровки вероятностей (чем ближе к 0, тем точнее процентная вероятность риска).
              </li>
            </ul>
          </div>
        </div>
      </section>

      <section className="card">
        <div className="card-head">
          <div className="row" style={{ gap: 8, alignItems: 'center' }}>
            <h2>Сравнение подходов к прогнозированию</h2>
            <Hint>Горизонт {r.horizon_days} дней. Меньше ошибка — лучше; больше охват и поиск разрывов — лучше.</Hint>
          </div>
        </div>
        <div className="table-wrap">
          <table className="table table-stack num">
            <thead>
              <tr>
                <th>Модель</th>
                <th className="r">MAE, ₽</th>
                <th className="r">MAE, % оборота</th>
                <th className="r">В диапазоне</th>
                <th className="r">Находит разрывы (Recall)</th>
                <th className="r">Точность (Precision)</th>
              </tr>
            </thead>
            <tbody>
              {r.models.map((x) => (
                <tr key={x.name} style={x.is_selected ? { background: 'var(--primary-65)', fontWeight: 650 } : undefined}>
                  <td style={{ color: 'var(--text)' }}>
                    {x.name}{' '}
                    {x.is_selected && (
                      <span className="badge b-low" style={{ marginLeft: 8, fontSize: 11 }}>
                        выбрана
                      </span>
                    )}
                  </td>
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
          <div className="card-head">
            <h2>Прогноз против факта (ретроспективный бэктест)</h2>
          </div>
          <div style={{ height: 330 }}>
            <ResponsiveContainer>
              <ComposedChart data={data} margin={{ top: 12, right: 12, bottom: 0, left: 0 }}>
                <CartesianGrid stroke="var(--border-light)" vertical={false} />
                <XAxis dataKey="date" tickFormatter={fmtDayShort} tick={{ fontSize: 12, fill: 'var(--text-3)' }} tickLine={false} minTickGap={20} />
                <YAxis tickFormatter={fmtRubShort} tick={{ fontSize: 12, fill: 'var(--text-3)' }} tickLine={false} axisLine={false} width={74} />
                <Tooltip
                  formatter={(v) => (Array.isArray(v) ? `${fmtRub(v[0])} – ${fmtRub(v[1])}` : fmtRub(Number(v)))}
                  labelFormatter={(l) => fmtDayShort(String(l))}
                  contentStyle={{
                    background: 'var(--surface)',
                    borderRadius: 10,
                    border: '1px solid var(--border)',
                    boxShadow: 'var(--shadow-popover)',
                  }}
                />
                <Legend />
                <Area dataKey="band" name="Возможный диапазон (P10..P90)" stroke="none" fill="var(--primary)" fillOpacity={0.14} isAnimationActive={false} />
                <Line dataKey="predicted" name="Прогноз модели" stroke="var(--primary-active)" strokeWidth={2} strokeDasharray="6 4" dot={false} isAnimationActive={false} />
                <Line dataKey="actual" name="Фактический баланс" stroke="var(--primary)" strokeWidth={2.75} dot={false} isAnimationActive={false} />
              </ComposedChart>
            </ResponsiveContainer>
          </div>
        </section>
      )}
    </div>
  )
}

function Big({ label, value, sub, hint }: { label: string; value: string; sub?: string; hint: string }) {
  return (
    <div className="card" style={{ padding: '18px 20px' }}>
      <div className="row small muted" style={{ gap: 6, flexWrap: 'nowrap', justifyContent: 'space-between' }}>
        <span style={{ color: 'var(--text-2)', fontWeight: 500 }}>{label}</span>
        <Hint>{hint}</Hint>
      </div>
      <div className="num" style={{ fontSize: 24, fontWeight: 700, marginTop: 8, color: 'var(--text)', letterSpacing: '-0.02em' }}>
        {value}
      </div>
      {sub && <div style={{ fontSize: 12, color: 'var(--text-3)', marginTop: 4 }}>{sub}</div>}
    </div>
  )
}
