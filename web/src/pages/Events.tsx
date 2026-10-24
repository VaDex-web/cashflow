import { useState, type FormEvent } from 'react'
import { api } from '../api/client'
import { EVENT_ICON, EVENT_LABEL } from '../components/BalanceChart'
import { Empty, ErrorBox, Loading, SourceBadge } from '../components/ui'
import { fmtDateTime, fmtDayWeek, fmtRub, toISO } from '../lib/format'
import { forecastSummary } from '../lib/risk'
import { useSession } from '../lib/session'
import { useAsync } from '../lib/useAsync'
import type { CashEvent, Direction, EventStatus, EventType, IntegrationName, NewCashEvent, UploadSourceName } from '../types'
import { NoCompany } from './Dashboard'

const INTEGRATIONS: { name: IntegrationName; icon: string; title: string; text: string }[] = [
  { name: 'bank', icon: '🏦', title: 'Банк Центр-Инвест', text: 'Новые операции по счёту каждый день' },
  { name: '1c', icon: '📒', title: '1С: Бухгалтерия', text: 'Выставленные счета, договоры, зарплата' },
  { name: 'tax_calendar', icon: '🧾', title: 'Налоговый календарь', text: 'Сроки и примерные суммы налогов' },
  { name: 'registry', icon: '📜', title: 'Открытые реестры', text: 'Госконтракты и данные о контрагентах' },
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
  { label: '🤝 Клиент обещал заплатить', direction: 'in', type: 'manual', note: 'Клиент обещал оплатить' },
  { label: '🛠 Закупка оборудования', direction: 'out', type: 'manual', note: 'Закупка оборудования' },
  { label: '📦 Крупная закупка товара', direction: 'out', type: 'invoice', note: 'Закупка товара у поставщика' },
  { label: '💰 Возврат долга', direction: 'in', type: 'manual', note: 'Возврат займа / долга' },
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
    <div className="grid" style={{ gap: 18 }}>
      <div className="page-head" style={{ marginBottom: 0 }}>
        <div>
          <h1>Платежи и источники</h1>
          <p>Чем больше мы знаем о будущих платежах, тем точнее прогноз.</p>
        </div>
      </div>

      {effect && (
        <div className="notice notice-info" role="status">
          <span>📈</span>
          <span>
            {effect.before === effect.after
              ? <>«{effect.what}»: прогноз не изменился — {effect.after}.</>
              : <>«{effect.what}» изменил прогноз: было — {effect.before}; <b>стало — {effect.after}</b>.</>}
          </span>
        </div>
      )}

      <section className="grid" style={{ gridTemplateColumns: 'repeat(auto-fit, minmax(230px, 1fr))', gap: 12 }}>
        {INTEGRATIONS.map((i) => {
          const st = synced[i.name]
          const server = status.data?.find((x) => x.name === i.name)
          const local = st && st !== 'busy' && 'at' in st ? st : null
          const lastSync = local?.at ?? server?.last_sync ?? null
          const message = local?.message ?? server?.message
          return (
            <div key={i.name} className="card" style={{ padding: 16, display: 'grid', gap: 8 }}>
              <div className="row" style={{ gap: 8 }}><span style={{ fontSize: 22 }}>{i.icon}</span><h3>{i.title}</h3></div>
              <p className="small muted">{i.text}</p>
              {lastSync && (
                <>
                  <div className="tiny" style={{ color: 'var(--ok)' }}>
                    ✓ Подключено · обновлено {fmtDateTime(lastSync)}
                    {local?.added != null ? ` · новых событий: ${local.added}` : server && server.events > 0 ? ` · событий: ${server.events}` : ''}
                  </div>
                  {message && <div className="tiny">{message}</div>}
                </>
              )}
              {st && st !== 'busy' && 'error' in st && <div className="tiny" style={{ color: 'var(--red)' }}>{st.error}</div>}
              <button className="btn btn-sm btn-ghost" onClick={() => sync(i.name, i.title)} disabled={st === 'busy'} style={{ justifySelf: 'start' }}>
                {st === 'busy' ? 'Синхронизируем…' : lastSync ? '🔄 Обновить' : '🔌 Подключить'}
              </button>
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
          {!ev.loading && !ev.error && list.length === 0 && <Empty icon="📅" title="Нет ожидаемых платежей">Подключите 1С или добавьте платёж вручную.</Empty>}
          {list.length > 0 && (
            <div className="table-wrap">
              <table className="table table-stack">
                <thead><tr><th>Дата</th><th>Что</th><th className="r">Сумма</th><th>Источник</th><th>Статус</th></tr></thead>
                <tbody>
                  {list.map((e) => (
                    <tr key={e.id}>
                      <td style={{ whiteSpace: 'nowrap' }}>{fmtDayWeek(e.date)}</td>
                      <td>
                        <div>{EVENT_ICON[e.type]} {e.counterparty ?? EVENT_LABEL[e.type]}</div>
                        {e.note && <div className="tiny clamp-2" title={e.note}>{e.note}</div>}
                      </td>
                      <td className="r num" style={{ whiteSpace: 'nowrap', fontWeight: 600, color: e.direction === 'in' ? 'var(--ok)' : 'var(--text)' }}>
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
    <form className="card" onSubmit={upload} style={{ display: 'grid', gap: 10 }}>
      <div className="card-head" style={{ marginBottom: 0 }}><h2>Загрузить файл источника</h2></div>
      <p className="small muted">Выгрузка из 1С, договоры или счета — ожидаемые платежи из файла сразу попадут в прогноз.</p>
      <div className="seg" style={{ justifySelf: 'start', flexWrap: 'wrap' }}>
        {UPLOADS.map((u) => (
          <button type="button" key={u.name} className={kind === u.name ? 'on' : ''} onClick={() => { setKind(u.name); setFile(null); setMsg(null) }}>{u.title}</button>
        ))}
      </div>
      <div className="tiny">{meta.hint}</div>
      <div className="row" style={{ gap: 8 }}>
        <label className="btn btn-ghost" style={{ cursor: 'pointer' }}>
          📎 Выбрать файл
          <input key={kind} type="file" accept={meta.accept} aria-label={`Файл: ${meta.title}`} hidden
            onChange={(e) => setFile(e.target.files?.[0] ?? null)} />
        </label>
        <span className="small muted" style={{ flex: 1, minWidth: 0, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
          {file ? file.name : 'файл не выбран'}
        </span>
        <button className="btn btn-lime" disabled={busy || !file}>{busy ? 'Загружаем…' : 'Загрузить'}</button>
      </div>
      {msg && <div className={`notice ${msg.ok ? 'notice-info' : 'notice-err'}`}>{msg.text}</div>}
    </form>
  )
}

function ManualForm({ companyId, track }: { companyId: string; track: Track }) {
  const tomorrow = (() => { const d = new Date(); d.setDate(d.getDate() + 1); return toISO(d) })()
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
    if (!sum || sum <= 0) { setMsg({ ok: false, text: 'Укажите сумму больше нуля' }); return }
    setBusy(true)
    setMsg(null)
    try {
      const created: CashEvent = await track('Платёж вручную', () => api.addEvent(companyId, {
        type, direction, amount: sum, date, source: 'manual', status: 'expected',
        counterparty: counterparty.trim() || undefined, note: note.trim() || undefined,
      }))
      setMsg({ ok: true, text: `Добавлено: ${direction === 'in' ? '+' : '−'}${fmtRub(created.amount)} на ${fmtDayWeek(created.date)}. Прогноз на главной учтёт этот платёж.` })
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
    <form className="card" onSubmit={submit} style={{ display: 'grid', gap: 12 }}>
      <h2>Добавить платёж вручную</h2>
      <p className="small muted">Знаете о платеже, которого нет в 1С? Добавьте — и прогноз его учтёт.</p>
      <PhraseInput companyId={companyId} track={track} />
      <div className="tiny" style={{ textAlign: 'center' }}>или заполните поля</div>
      <div className="row" style={{ gap: 6 }}>
        {TEMPLATES.map((t) => (
          <button type="button" key={t.label} className="btn btn-sm btn-ghost" onClick={() => applyTemplate(t)}>{t.label}</button>
        ))}
      </div>
      <div className="seg" style={{ justifySelf: 'start' }}>
        <button type="button" className={direction === 'in' ? 'on' : ''} onClick={() => setDirection('in')}>⬇ Поступление</button>
        <button type="button" className={direction === 'out' ? 'on' : ''} onClick={() => setDirection('out')}>⬆ Списание</button>
      </div>
      <div className="grid-2" style={{ gap: 10 }}>
        <label className="field">Дата<input className="input" type="date" value={date} onChange={(e) => setDate(e.target.value)} required /></label>
        <label className="field">Сумма, ₽<input className="input num" inputMode="decimal" placeholder="150 000" value={amount} onChange={(e) => setAmount(e.target.value)} required /></label>
      </div>
      <label className="field">Контрагент<input className="input" placeholder="ООО «Ромашка»" value={counterparty} onChange={(e) => setCounterparty(e.target.value)} /></label>
      <label className="field">Комментарий<input className="input" placeholder="Например: обещали оплатить до пятницы" value={note} onChange={(e) => setNote(e.target.value)} /></label>
      {msg && <div className={`notice ${msg.ok ? 'notice-info' : 'notice-err'}`}>{msg.text}</div>}
      <button className="btn btn-lime" disabled={busy}>{busy ? 'Сохраняем…' : 'Добавить платёж'}</button>
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
      setMsg({ ok: true, text: `Добавлено: ${created.direction === 'in' ? '+' : '−'}${fmtRub(created.amount)} на ${fmtDayWeek(created.date)}. Прогноз учтёт этот платёж.` })
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
        <input className="input" placeholder="Например: клиент обещал заплатить 300 000 ₽ 20-го" value={text}
          onChange={(e) => { setText(e.target.value); setDraft(null) }} aria-label="Платёж обычной фразой"
          onKeyDown={(e) => { if (e.key === 'Enter') { e.preventDefault(); void parse() } }} />
        <button type="button" className="btn btn-ghost" onClick={() => void parse()} disabled={busy || text.trim().length < 3}>Разобрать</button>
      </div>
      {draft && (
        <div className="notice notice-info" style={{ alignItems: 'center' }}>
          <span style={{ flex: 1 }}>Поняли так: <b>{draft.understood}</b></span>
          <button type="button" className="btn btn-sm btn-lime" onClick={save} disabled={busy}>Добавить</button>
        </div>
      )}
      {msg && <div className={`notice ${msg.ok ? 'notice-info' : 'notice-err'}`}>{msg.text}</div>}
    </div>
  )
}
