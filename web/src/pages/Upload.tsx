import { useRef, useState, type DragEvent } from 'react'
import { useNavigate } from 'react-router-dom'
import { api } from '../api/client'
import { useSession } from '../lib/session'

const MAX_MB = 20
const REQUIRED_HINT = 'дата, сумма, направление (поступление/списание), контрагент, ИНН, назначение платежа, остаток'

/** Быстрая проверка в браузере — чтобы сразу сказать человеку, что не так с файлом */
async function precheck(file: File): Promise<string | null> {
  if (!/\.(csv|txt)$/i.test(file.name)) return `Файл «${file.name}» не похож на CSV. Выгрузите выписку из интернет-банка в формате CSV.`
  if (file.size === 0) return 'Файл пустой.'
  if (file.size > MAX_MB * 1024 * 1024) return `Файл больше ${MAX_MB} МБ. Выгрузите выписку за меньший период.`
  const head = (await file.slice(0, 4096).text()).split(/\r?\n/)[0] ?? ''
  if (head.includes('�')) return 'Файл в неподдерживаемой кодировке. Сохраните его в UTF-8 (в Excel: «Сохранить как» → «CSV UTF-8»).'
  if (!/[;,\t]/.test(head)) return 'Не удалось найти столбцы. В первой строке должны быть названия колонок, разделённые запятой или точкой с запятой.'
  const h = head.toLowerCase()
  if (!/(date|дата)/.test(h)) return `Не нашли колонку с датой. Нужны колонки: ${REQUIRED_HINT}.`
  if (!/(amount|сумма|приход|расход|дебет|кредит)/.test(h)) return `Не нашли колонку с суммой. Нужны колонки: ${REQUIRED_HINT}.`
  return null
}

export function Upload() {
  const { setCompany, companyId } = useSession()
  const nav = useNavigate()
  const input = useRef<HTMLInputElement>(null)
  const [drag, setDrag] = useState(false)
  const [file, setFile] = useState<File | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  async function handle(f: File | undefined) {
    if (!f) return
    setFile(f)
    setError(await precheck(f))
  }

  async function send() {
    if (!file) return
    setBusy(true)
    setError(null)
    try {
      const r = await api.uploadStatement(file)
      setCompany(r.company_id)
      nav('/')
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setBusy(false)
    }
  }

  function onDrop(e: DragEvent) {
    e.preventDefault()
    setDrag(false)
    void handle(e.dataTransfer.files[0])
  }

  return (
    <div style={{ maxWidth: 720 }}>
      <div className="page-head">
        <div>
          <h1>Загрузите выписку по счёту</h1>
          <p>Мы посмотрим, как двигались деньги, и покажем, что будет с остатком в ближайший месяц.</p>
        </div>
      </div>

      <div
        className="card"
        onDragOver={(e) => { e.preventDefault(); setDrag(true) }}
        onDragLeave={() => setDrag(false)}
        onDrop={onDrop}
        onClick={() => input.current?.click()}
        role="button"
        tabIndex={0}
        onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') input.current?.click() }}
        style={{
          borderStyle: 'dashed', borderWidth: 2, borderColor: drag ? 'var(--lime-600)' : 'var(--border)',
          background: drag ? 'var(--lime-100)' : 'var(--surface)', textAlign: 'center', padding: '44px 20px', cursor: 'pointer',
        }}
      >
        <div style={{ fontSize: 40 }}>📄</div>
        <h2 style={{ margin: '10px 0 6px' }}>{file ? file.name : 'Перетащите сюда файл выписки'}</h2>
        <p className="muted">{file ? `${(file.size / 1024).toFixed(0)} КБ` : 'или нажмите, чтобы выбрать файл · формат CSV'}</p>
        <input ref={input} type="file" accept=".csv,.txt,text/csv" hidden onChange={(e) => void handle(e.target.files?.[0])} />
      </div>

      {error && <div className="notice notice-err" style={{ marginTop: 14 }} role="alert"><span>⚠️</span><span>{error}</span></div>}

      <div className="row" style={{ marginTop: 16 }}>
        <button className="btn btn-lime" disabled={!file || !!error || busy} onClick={send}>
          {busy ? 'Считаем прогноз…' : 'Построить прогноз'}
        </button>
        {companyId && <button className="btn btn-ghost" onClick={() => nav('/')}>Вернуться к прогнозу</button>}
      </div>

      <div className="card" style={{ marginTop: 24 }}>
        <h3>Какой файл подойдёт</h3>
        <ul className="small muted" style={{ margin: '8px 0 0', paddingLeft: 18, display: 'grid', gap: 4 }}>
          <li>Выписка из интернет-банка в формате CSV, лучше всего — за 3–6 месяцев.</li>
          <li>Колонки: {REQUIRED_HINT}. Названия могут отличаться — мы разберёмся.</li>
          <li>Сумма может быть со знаком «минус» для списаний — это тоже нормально.</li>
          <li>Дубли и пустые строки мы уберём сами.</li>
        </ul>
      </div>
    </div>
  )
}
