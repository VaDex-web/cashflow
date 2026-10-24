import { useState, type FormEvent } from 'react'
import { api } from '../api/client'
import { EVENT_LABEL } from '../components/BalanceChart'
import { Empty, ErrorBox, Loading, SourceBadge } from '../components/ui'
import { fmtDateTime, fmtDayWeek, fmtRub, toISO } from '../lib/format'
import { forecastSummary } from '../lib/risk'
import { useSession } from '../lib/session'
import { useAsync } from '../lib/useAsync'
import type { CashEvent, Direction, EventStatus, EventType, IntegrationName, NewCashEvent, UploadSourceName } from '../types'
import { NoCompany } from './Dashboard'

function IntegrationIcon({ name }: { name: IntegrationName }) {
  const size = 22
  switch (name) {
    case 'bank':
      return (
        <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="var(--primary)" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
          <path d="M3 21h18M3 10h18M5 10v11M19 10v11M9 10v11M14 10v11M12 3 2 10h20Z" />
        </svg>
      )
    case '1c':
      return (
        <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="#d70f00" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
          <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
          <polyline points="14 2 14 8 20 8" />
          <line x1="16" y1="13" x2="8" y2="13" />
          <line x1="16" y1="17" x2="8" y2="17" />
        </svg>
      )
    case 'tax_calendar':
      return (
        <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="#1e6091" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
          <rect x="3" y="4" width="18" height="18" rx="2" ry="2" />
          <line x1="16" y1="2" x2="16" y2="6" />
          <line x1="8" y1="2" x2="8" y2="6" />
          <line x1="3" y1="10" x2="21" y2="10" />
        </svg>
      )
    case 'registry':
      return (
        <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="#7B4FB0" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
          <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z" />
        </svg>
      )
  }
}

function EventTypeIcon({ type }: { type: EventType }) {
  const size = 15
  switch (type) {
    case 'payroll':
      return (
        <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" style={{ flexShrink: 0 }}>
          <path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2" />
          <circle cx="9" cy="7" r="4" />
          <path d="M23 21v-2a4 4 0 0 0-3-3.87" />
          <path d="M16 3.13a4 4 0 0 1 0 7.75" />
        </svg>
      )
    case 'tax':
      return (
        <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" style={{ flexShrink: 0 }}>
          <rect x="3" y="4" width="18" height="18" rx="2" ry="2" />
          <line x1="16" y1="2" x2="16" y2="6" />
          <line x1="8" y1="2" x2="8" y2="6" />
          <line x1="3" y1="10" x2="21" y2="10" />
        </svg>
      )
    case 'loan':
      return (
        <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" style={{ flexShrink: 0 }}>
          <path d="M3 21h18M3 10h18M5 10v11M19 10v11M9 10v11M14 10v11M12 3 2 10h20Z" />
        </svg>
      )
    case 'contract':
      return (
        <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" style={{ flexShrink: 0 }}>
          <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
          <polyline points="14 2 14 8 20 8" />
          <line x1="16" y1="13" x2="8" y2="13" />
          <line x1="16" y1="17" x2="8" y2="17" />
        </svg>
      )
    case 'invoice':
      return (
        <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" style={{ flexShrink: 0 }}>
          <path d="M4 2v20l2-1 2 1 2-1 2 1 2-1 2 1 2-1 2 1 2-1 2 1V2l-2 1-2-1-2 1-2-1-2 1-2-1-2 1-2-1-2 1Z" />
          <line x1="8" y1="8" x2="16" y2="8" />
          <line x1="8" y1="12" x2="16" y2="12" />
        </svg>
      )
    case 'manual':
      return (
        <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" style={{ flexShrink: 0 }}>
          <path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7" />
          <path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z" />
        </svg>
      )
  }
}

const INTEGRATIONS: { name: IntegrationName; title: string; text: string }[] = [
  { name: 'bank', title: 'Банк Центр-Инвест', text: 'Новые операции по счёту каждый день' },
  { name: '1c', title: '1С: Бухгалтерия', text: 'Выставленные счета, договоры, зарплата' },
  { name: 'tax_calendar', title: 'Налоговый календарь', text: 'Сроки и примерные суммы налогов' },
  { name: 'registry', title: 'Открытые реестры', text: 'Госконтракты и данные о контрагентах' },
]

const UPLOADS: { name: UploadSourceName; title: string; hint: string; accept: string }[] = [
  { name: '1c', title: 'Выгрузка из 1С', hint: 'JSON-выгрузка: счета, договоры, зарплата, налоги', accept: '.json' },
  { name: 'contracts', title: 'Договоры', hint: 'CSV или JSON: контрагент, сумма, график оплат', accept: '.csv,.json' },
  { name: 'invoices', title: 'Счета', hint: 'CSV или JSON: номер, контрагент, сумма, срок оплаты', accept: '.csv,.json' },
]

type Track = <T>(what: string, action: () => Promise<T>) => Promise<T>

const STATUS: Record<EventStatus, { label: string; cls: string }> = {
  expected: { label: 'Ожидается', cls: 'b-neutral' },
  paid: { label: 'Оплачено', cls: 'b-low' },
  overdue: { label: 'Просрочено', cls: 'b-high' },
}

const TEMPLATES: { label: string; direction: Direction; type: EventType; note: string }[] = [
  { label: 'Клиент обещал оплатить', direction: 'in', type: 'manual', note: 'Клиент обещал оплатить' },
  { label: 'Закупка оборудования', direction: 'out', type: 'manual', note: 'Закупка оборудования' },
  { label: 'Крупная закупка товара', direction: 'out', type: 'invoice', note: 'Закупка товара у поставщика' },
  { label: 'Возврат займа / долга', direction: 'in', type: 'manual', note: 'Возврат займа / долга' },
]

export function Events() {
  const { companyId } = useSession()
  const ev = useAsync(() => (companyId ? api.events(companyId) : Promise.resolve([])), [companyId])
  const status = useAsync(() => (companyId ? api.integrations(companyId) : Promise.resolve([])), [companyId])
  const [synced, setSynced] = useState<Record<string, { at: string; added?: number; message?: string } | 'busy' | { error: string }>>({})
  const [filter, setFilter] = useState<'upcoming' | 'all'>('upcoming')
  const [effect, setEffect] = useState<{ what: string; before: string; after: string } | null>(null)

  if (!companyId) return <NoCompany />
  const cid = companyId

  const track: Track = async (what, action) => {
    const before = await api.forecast(cid).then(forecastSummary).catch(() => null)
    const result = await action()
    const after = await api.forecast(cid).then(forecastSummary).catch(() => null)
    if (before && after) setEffect({ what, before, after })
    ev.reload()
    status.reload()
    return result
  }

  async function sync(name: IntegrationName, title: string) {
    setSynced((s) => ({ ...s, [name]: 'busy' }))
    try {
      const r = await track(title, () => api.sync(cid, name))
      setSynced((s) => ({ ...s, [name]: { at: r.synced_at ?? new Date().toISOString(), added: r.events_added, message: r.message } }))
    } catch (e) {
      setSynced((s) => ({ ...s, [name]: { error: e instanceof Error ? e.message : String(e) } }))
    }
  }

  const list = [...(ev.data ?? [])]
    .filter((e) => filter === 'all' || e.status !== 'paid')
    .sort((a, b) => a.date.localeCompare(b.date))

  return (
    <div className="grid" style={{ gap: 20 }}>
      <div className="page-head" style={{ marginBottom: 0 }}>
        <div>
          <h1>Платежи и источники</h1>
          <p>Чем полнее данные о будущих списаниях и поступлениях, тем точнее прогноз остатка.</p>
        </div>
      </div>

      {effect && (
        <div className="notice notice-info" role="status" style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
          <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" style={{ flexShrink: 0 }}>
            <line x1="18" x2="18" y1="20" y2="10" />
            <line x1="12" x2="12" y1="20" y2="4" />
            <line x1="6" x2="6" y1="20" y2="14" />
          </svg>
          <span>
            {effect.before === effect.after ? (
              <>«{effect.what}»: прогноз не изменился — {effect.after}.</>
            ) : (
              <>
                «{effect.what}» изменил прогноз: было — {effect.before}; <b>стало — {effect.after}</b>.
              </>
            )}
          </span>
        </div>
      )}

      <section className="grid" style={{ gridTemplateColumns: 'repeat(auto-fit, minmax(240px, 1fr))', gap: 14 }}>
        {INTEGRATIONS.map((i) => {
          const st = synced[i.name]
          const server = status.data?.find((x) => x.name === i.name)
          const local = st && st !== 'busy' && 'at' in st ? st : null
          const lastSync = local?.at ?? server?.last_sync ?? null
          const message = local?.message ?? server?.message
          return (
            <div key={i.name} className="card" style={{ padding: '18px 20px', display: 'flex', flexDirection: 'column', gap: 10 }}>
              <div className="row" style={{ gap: 10, alignItems: 'center' }}>
                <div style={{ width: 36, height: 36, borderRadius: 10, background: 'var(--surface-subtle)', display: 'grid', placeItems: 'center', flexShrink: 0 }}>
                  <IntegrationIcon name={i.name} />
                </div>
                <h3 style={{ fontSize: 15 }}>{i.title}</h3>
              </div>
              <p className="small muted" style={{ lineHeight: 1.45, flex: 1 }}>{i.text}</p>
              {lastSync && (
                <div style={{ marginTop: 2 }}>
                  <div className="tiny" style={{ color: 'var(--ok-accent)', fontWeight: 500 }}>
                    ✓ Подключено · {fmtDateTime(lastSync)}
                    {local?.added != null ? ` · новых: ${local.added}` : server && server.events > 0 ? ` · событий: ${server.events}` : ''}
                  </div>
                  {message && <div className="tiny muted" style={{ marginTop: 2 }}>{message}</div>}
                </div>
              )}
              {st && st !== 'busy' && 'error' in st && (
                <div className="tiny" style={{ color: 'var(--danger)' }}>{st.error}</div>
              )}
              <div style={{ marginTop: 6 }}>
                <button
                  type="button"
                  className="btn btn-sm btn-ghost"
                  onClick={() => sync(i.name, i.title)}
                  disabled={st === 'busy'}
                >
                  {st === 'busy' ? 'Синхронизируем…' : lastSync ? 'Обновить' : 'Подключить'}
                </button>
              </div>
            </div>
          )
        })}
      </section>

      <SourceUpload companyId={cid} track={track} />

      <div className="grid-main">
        <section className="card">
          <div className="card-head">
            <h2>Ожидаемые платежи</h2>
            <div className="seg">
              <button className={filter === 'upcoming' ? 'on' : ''} onClick={() => setFilter('upcoming')}>Предстоящие</button>
              <button className={filter === 'all' ? 'on' : ''} onClick={() => setFilter('all')}>Все</button>
            </div>
          </div>
          {ev.loading && <Loading height={300} />}
          {ev.error && <ErrorBox message={ev.error} onRetry={ev.reload} />}
          {!ev.loading && !ev.error && list.length === 0 && (
            <Empty title="Нет ожидаемых платежей">Подключите 1С или добавьте платёж вручную.</Empty>
          )}
          {list.length > 0 && (
            <div className="table-wrap">
              <table className="table table-stack">
                <thead>
                  <tr>
                    <th>Дата</th>
                    <th>Назначение / Контрагент</th>
                    <th className="r">Сумма</th>
                    <th>Источник</th>
                    <th>Статус</th>
                  </tr>
                </thead>
                <tbody>
                  {list.map((e) => (
                    <tr key={e.id}>
                      <td style={{ whiteSpace: 'nowrap', fontWeight: 500 }}>{fmtDayWeek(e.date)}</td>
                      <td>
                        <div style={{ display: 'flex', alignItems: 'center', gap: 6, fontWeight: 500, color: 'var(--text)' }}>
                          <EventTypeIcon type={e.type} />
                          <span>{e.counterparty ?? EVENT_LABEL[e.type]}</span>
                        </div>
                        {e.note && <div className="tiny clamp-2" style={{ color: 'var(--text-3)', marginTop: 2 }} title={e.note}>{e.note}</div>}
                      </td>
                      <td className="r num" style={{ whiteSpace: 'nowrap', fontWeight: 600, color: e.direction === 'in' ? 'var(--ok-accent)' : 'var(--text)' }}>
                        {e.direction === 'in' ? '+' : '−'}{fmtRub(e.amount)}
                      </td>
                      <td><SourceBadge s={e.source} /></td>
                      <td><span className={`badge ${STATUS[e.status].cls}`}>{STATUS[e.status].label}</span></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </section>

        <ManualForm companyId={cid} track={track} />
      </div>
    </div>
  )
}

function SourceUpload({ companyId, track }: { companyId: string; track: Track }) {
  const [kind, setKind] = useState<UploadSourceName>('1c')
  const [file, setFile] = useState<File | null>(null)
  const [busy, setBusy] = useState(false)
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null)
  const meta = UPLOADS.find((u) => u.name === kind)!

  async function upload(e: FormEvent) {
    e.preventDefault()
    if (!file) return
    setBusy(true)
    setMsg(null)
    try {
      const r = await track(meta.title, () => api.uploadSource(companyId, kind, file))
      setMsg({ ok: true, text: r.message || `Файл «${file.name}» загружен, новых событий: ${r.events_added ?? 0}.` })
      setFile(null)
    } catch (err) {
      setMsg({ ok: false, text: err instanceof Error ? err.message : String(err) })
    } finally {
      setBusy(false)
    }
  }

  return (
    <form className="card" onSubmit={upload} style={{ display: 'grid', gap: 12, padding: '22px 24px' }}>
      <div className="card-head" style={{ marginBottom: 0 }}>
        <h2>Загрузить файл источника</h2>
      </div>
      <p className="small muted">Выгрузка из 1С, реестр договоров или счетов — платежи из файла сразу добавятся в модель прогноза.</p>
      <div className="seg" style={{ justifySelf: 'start', flexWrap: 'wrap' }}>
        {UPLOADS.map((u) => (
          <button
            type="button"
            key={u.name}
            className={kind === u.name ? 'on' : ''}
            onClick={() => {
              setKind(u.name)
              setFile(null)
              setMsg(null)
            }}
          >
            {u.title}
          </button>
        ))}
      </div>
      <div className="tiny muted">{meta.hint}</div>
      <div className="row" style={{ gap: 10, flexWrap: 'wrap', alignItems: 'center' }}>
        <label className="btn btn-ghost" style={{ cursor: 'pointer', display: 'inline-flex', alignItems: 'center', gap: 8 }}>
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <path d="m21.44 11.05-9.19 9.19a6 6 0 0 1-8.49-8.49l8.57-8.57A4 4 0 1 1 18 8.84l-8.59 8.57a2 2 0 0 1-2.83-2.83l8.49-8.48" />
          </svg>
          Выбрать файл
          <input
            key={kind}
            type="file"
            accept={meta.accept}
            aria-label={`Файл: ${meta.title}`}
            hidden
            onChange={(e) => setFile(e.target.files?.[0] ?? null)}
          />
        </label>
        <span className="small muted" style={{ flex: 1, minWidth: 0, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
          {file ? file.name : 'файл не выбран'}
        </span>
        <button className="btn btn-lime" disabled={busy || !file}>
          {busy ? 'Загружаем…' : 'Загрузить'}
        </button>
      </div>
      {msg && (
        <div className={`notice ${msg.ok ? 'notice-info' : 'notice-err'}`} style={{ marginTop: 4 }}>
          {msg.text}
        </div>
      )}
    </form>
  )
}

function ManualForm({ companyId, track }: { companyId: string; track: Track }) {
  const tomorrow = (() => {
    const d = new Date()
    d.setDate(d.getDate() + 1)
    return toISO(d)
  })()
  const [date, setDate] = useState(tomorrow)
  const [amount, setAmount] = useState('')
  const [direction, setDirection] = useState<Direction>('in')
  const [type, setType] = useState<EventType>('manual')
  const [counterparty, setCounterparty] = useState('')
  const [note, setNote] = useState('')
  const [busy, setBusy] = useState(false)
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null)

  function applyTemplate(t: (typeof TEMPLATES)[number]) {
    setDirection(t.direction)
    setType(t.type)
    setNote(t.note)
  }

  async function submit(e: FormEvent) {
    e.preventDefault()
    const sum = Number(amount.replace(/\s/g, '').replace(',', '.'))
    if (!sum || sum <= 0) {
      setMsg({ ok: false, text: 'Укажите сумму больше нуля' })
      return
    }
    setBusy(true)
    setMsg(null)
    try {
      const created: CashEvent = await track('Платёж вручную', () =>
        api.addEvent(companyId, {
          type,
          direction,
          amount: sum,
          date,
          source: 'manual',
          status: 'expected',
          counterparty: counterparty.trim() || undefined,
          note: note.trim() || undefined,
        }),
      )
      setMsg({
        ok: true,
        text: `Добавлено: ${direction === 'in' ? '+' : '−'}${fmtRub(created.amount)} на ${fmtDayWeek(created.date)}. Прогноз обновлён.`,
      })
      setAmount('')
      setCounterparty('')
      setNote('')
    } catch (err) {
      setMsg({ ok: false, text: err instanceof Error ? err.message : String(err) })
    } finally {
      setBusy(false)
    }
  }

  return (
    <form className="card" onSubmit={submit} style={{ display: 'grid', gap: 14, padding: '22px 24px' }}>
      <h2 style={{ fontSize: 17 }}>Добавить платёж вручную</h2>
      <p className="small muted">Знаете о разовом или внеплановом платеже? Добавьте его, чтобы прогноз учитывал его в балансе.</p>

      <PhraseInput companyId={companyId} track={track} />

      <div className="tiny muted" style={{ textAlign: 'center', position: 'relative', margin: '4px 0' }}>
        <span>или заполните форму</span>
      </div>

      <div className="row" style={{ gap: 6 }}>
        {TEMPLATES.map((t) => (
          <button
            type="button"
            key={t.label}
            className="btn btn-sm btn-ghost"
            style={{ fontSize: 12, padding: '4px 10px' }}
            onClick={() => applyTemplate(t)}
          >
            {t.label}
          </button>
        ))}
      </div>

      <div className="seg" style={{ justifySelf: 'start' }}>
        <button type="button" className={direction === 'in' ? 'on' : ''} onClick={() => setDirection('in')}>
          Поступление
        </button>
        <button type="button" className={direction === 'out' ? 'on' : ''} onClick={() => setDirection('out')}>
          Списание
        </button>
      </div>

      <div className="grid-2" style={{ gap: 12 }}>
        <label className="field">
          <span>Дата</span>
          <input className="input" type="date" value={date} onChange={(e) => setDate(e.target.value)} required />
        </label>
        <label className="field">
          <span>Сумма, ₽</span>
          <input
            className="input num"
            inputMode="decimal"
            placeholder="150 000"
            value={amount}
            onChange={(e) => setAmount(e.target.value)}
            required
          />
        </label>
      </div>

      <label className="field">
        <span>Контрагент</span>
        <input className="input" placeholder="ООО «Контрагент»" value={counterparty} onChange={(e) => setCounterparty(e.target.value)} />
      </label>

      <label className="field">
        <span>Комментарий</span>
        <input className="input" placeholder="Например: подтвердили оплату до пятницы" value={note} onChange={(e) => setNote(e.target.value)} />
      </label>

      {msg && <div className={`notice ${msg.ok ? 'notice-info' : 'notice-err'}`}>{msg.text}</div>}

      <button className="btn btn-lime" disabled={busy} style={{ justifySelf: 'start', marginTop: 4 }}>
        {busy ? 'Сохраняем…' : 'Добавить платёж'}
      </button>
    </form>
  )
}

function PhraseInput({ companyId, track }: { companyId: string; track: Track }) {
  const [text, setText] = useState('')
  const [draft, setDraft] = useState<{ event: NewCashEvent; understood: string } | null>(null)
  const [busy, setBusy] = useState(false)
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null)

  async function parse() {
    if (text.trim().length < 3) return
    setBusy(true)
    setMsg(null)
    try {
      setDraft(await api.parseEvent(companyId, text.trim()))
    } catch (err) {
      setDraft(null)
      setMsg({ ok: false, text: err instanceof Error ? err.message : String(err) })
    } finally {
      setBusy(false)
    }
  }

  async function save() {
    if (!draft) return
    setBusy(true)
    try {
      const created = await track('Платёж из фразы', () => api.addEvent(companyId, draft.event))
      setMsg({
        ok: true,
        text: `Добавлено: ${created.direction === 'in' ? '+' : '−'}${fmtRub(created.amount)} на ${fmtDayWeek(created.date)}. Прогноз обновлён.`,
      })
      setDraft(null)
      setText('')
    } catch (err) {
      setMsg({ ok: false, text: err instanceof Error ? err.message : String(err) })
    } finally {
      setBusy(false)
    }
  }

  return (
    <div style={{ display: 'grid', gap: 8 }}>
      <div className="row" style={{ gap: 8, flexWrap: 'nowrap' }}>
        <input
          className="input"
          placeholder="Быстрый ввод: «клиент заплатит 300 000 ₽ 20-го»"
          value={text}
          onChange={(e) => {
            setText(e.target.value)
            setDraft(null)
          }}
          aria-label="Платёж обычной фразой"
          onKeyDown={(e) => {
            if (e.key === 'Enter') {
              e.preventDefault()
              void parse()
            }
          }}
        />
        <button
          type="button"
          className="btn btn-ghost"
          onClick={() => void parse()}
          disabled={busy || text.trim().length < 3}
          style={{ flexShrink: 0 }}
        >
          Распознать
        </button>
      </div>
      {draft && (
        <div className="notice notice-info" style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
          <span style={{ flex: 1, fontSize: 13 }}>
            Распознано: <b>{draft.understood}</b>
          </span>
          <button type="button" className="btn btn-sm btn-lime" onClick={save} disabled={busy}>
            Добавить
          </button>
        </div>
      )}
      {msg && <div className={`notice ${msg.ok ? 'notice-info' : 'notice-err'}`}>{msg.text}</div>}
    </div>
  )
}
