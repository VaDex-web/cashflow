import { useRef, useState, type DragEvent } from 'react'
import { useNavigate } from 'react-router-dom'
import { api } from '../api/client'
import { useSession } from '../lib/session'

const MAX_MB = 20
const REQUIRED_HINT = 'дата, сумма, направление (поступление/списание), контрагент, ИНН, назначение платежа, остаток'

async function readCsvChunk(file: File, bytes = 8192): Promise<string> {
  const slice = file.slice(0, bytes)
  const buf = await slice.arrayBuffer()
  try {
    const dec = new TextDecoder('utf-8', { fatal: true })
    return dec.decode(buf, { stream: true }).replace(/^\ufeff/, '')
  } catch {
    try {
      const dec = new TextDecoder('windows-1251')
      return dec.decode(buf).replace(/^\ufeff/, '')
    } catch {
      return new TextDecoder('utf-8').decode(buf).replace(/^\ufeff/, '')
    }
  }
}

async function precheck(file: File): Promise<string | null> {
  if (!/\.(csv|txt)$/i.test(file.name)) return `Файл «${file.name}» не похож на CSV. Выгрузите выписку из интернет-банка в формате CSV.`
  if (file.size === 0) return 'Файл пустой.'
  if (file.size > MAX_MB * 1024 * 1024) return `Файл больше ${MAX_MB} МБ. Выгрузите выписку за меньший период.`
  const head = (await readCsvChunk(file)).split(/\r?\n/)[0] ?? ''
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
    <div style={{ maxWidth: 740 }}>
      <div className="page-head">
        <div>
          <h1>Загрузите выписку по счёту</h1>
          <p>Мы посмотрим, как двигались деньги, и покажем, что будет с остатком в ближайший месяц.</p>
        </div>
      </div>

      <div
        className="card"
        onDragOver={(e) => {
          e.preventDefault()
          setDrag(true)
        }}
        onDragLeave={() => setDrag(false)}
        onDrop={onDrop}
        onClick={() => input.current?.click()}
        role="button"
        tabIndex={0}
        onKeyDown={(e) => {
          if (e.key === 'Enter' || e.key === ' ') input.current?.click()
        }}
        style={{
          borderStyle: 'dashed',
          borderWidth: 2,
          borderColor: drag ? 'var(--primary)' : file ? 'var(--primary)' : 'var(--border)',
          background: drag ? 'var(--primary-65)' : file ? 'var(--surface-subtle)' : 'var(--surface)',
          textAlign: 'center',
          padding: '48px 24px',
          cursor: 'pointer',
          borderRadius: 'var(--radius-xl)',
          transition: 'all 0.15s ease-in-out',
        }}
      >
        <div
          style={{
            width: 56,
            height: 56,
            borderRadius: '50%',
            background: file ? 'var(--primary-60)' : 'var(--surface-subtle)',
            color: file ? 'var(--primary-active)' : 'var(--text-2)',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            margin: '0 auto 16px',
          }}
        >
          {file ? (
            <svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
              <polyline points="14 2 14 8 20 8" />
              <path d="m9 15 2 2 4-4" />
            </svg>
          ) : (
            <svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />
              <polyline points="17 8 12 3 7 8" />
              <line x1="12" y1="3" x2="12" y2="15" />
            </svg>
          )}
        </div>

        <h2 style={{ margin: '0 0 8px', fontSize: 18, color: 'var(--text)' }}>
          {file ? file.name : 'Перетащите сюда файл выписки'}
        </h2>
        <p className="muted" style={{ margin: 0, fontSize: 14 }}>
          {file ? (
            <span style={{ color: 'var(--primary-active)', fontWeight: 600 }}>
              {(file.size / 1024).toFixed(0)} КБ · Готов к обработке
            </span>
          ) : (
            'или нажмите для выбора файла · формат CSV / TXT'
          )}
        </p>
        <input ref={input} type="file" accept=".csv,.txt,text/csv" hidden onChange={(e) => void handle(e.target.files?.[0])} />
      </div>

      {error && (
        <div className="notice notice-err" style={{ marginTop: 16, display: 'flex', alignItems: 'center', gap: 10 }} role="alert">
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" style={{ flexShrink: 0 }}>
            <circle cx="12" cy="12" r="10" />
            <line x1="12" y1="8" x2="12" y2="12" />
            <line x1="12" y1="16" x2="12.01" y2="16" />
          </svg>
          <span>{error}</span>
        </div>
      )}

      <div className="row" style={{ marginTop: 20, gap: 12 }}>
        <button className="btn btn-lime" disabled={!file || !!error || busy} onClick={send}>
          {busy ? 'Построение прогноза…' : 'Построить прогноз'}
        </button>
        <button
          type="button"
          className="btn btn-ghost"
          onClick={() => {
            setCompany('demo-yuzhny-vkus')
            nav('/')
          }}
        >
          Загрузить демо-данные
        </button>
        {companyId && (
          <button className="btn btn-ghost" onClick={() => nav('/')}>
            Вернуться к прогнозу
          </button>
        )}
      </div>

      <div className="card" style={{ marginTop: 24, padding: '22px 24px' }}>
        <h3 style={{ fontSize: 16, marginBottom: 12 }}>Требования к выписке</h3>
        <ul className="small muted" style={{ margin: 0, paddingLeft: 18, display: 'grid', gap: 6, lineHeight: 1.5 }}>
          <li>Стандартная выписка из интернет-банка в формате CSV (оптимально за 3–6 месяцев).</li>
          <li>Обязательные поля: {REQUIRED_HINT}. Названия колонок могут варьироваться — сервис распознает их автоматически.</li>
          <li>Сумма может быть со знаком «минус» для списаний — это обрабатывается корректно.</li>
          <li>Повторные строки и пустые разделители фильтруются системой автоматически.</li>
        </ul>
      </div>
    </div>
  )
}
