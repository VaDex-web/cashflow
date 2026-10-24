import { useState, type FormEvent } from 'react'
import { useNavigate } from 'react-router-dom'
import { api, USE_MOCK } from '../api/client'
import { useSession } from '../lib/session'

export function Login() {
  const { login, companyId, setCompany } = useSession()
  const nav = useNavigate()
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  async function enter(token: string, keepCompany: boolean) {
    login(token)
    let company = keepCompany ? companyId : null
    try {
      const me = await api.me()
      if (me.company_id) company = me.company_id
    } catch {}
    setCompany(company)
    nav(company ? '/' : '/upload')
  }

  async function demo() {
    setBusy(true)
    setError(null)
    try {
      await enter((await api.demoLogin()).access_token, false)
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    } finally {
      setBusy(false)
    }
  }

  async function submit(e: FormEvent) {
    e.preventDefault()
    setBusy(true)
    setError(null)
    try {
      await enter((await api.login(username.trim(), password)).access_token, true)
    } catch (err) {
      setError(err instanceof Error && 'status' in err && (err as { status: number }).status === 401
        ? 'Неверный логин или пароль'
        : err instanceof Error ? err.message : String(err))
    } finally {
      setBusy(false)
    }
  }

  return (
    <div style={{ minHeight: '100vh', display: 'grid', placeItems: 'center', padding: 16, background: 'linear-gradient(160deg, #0b3d2e 0%, #11553f 55%, #6fa62a 140%)' }}>
      <form onSubmit={submit} className="card" style={{ width: 400, maxWidth: '100%', padding: 28, display: 'grid', gap: 16 }}>
        <div className="row" style={{ gap: 12 }}>
          <div className="brand-mark" style={{ width: 44, height: 44, fontSize: 20 }}>₽</div>
          <div>
            <h2>Денежный прогноз</h2>
            <div className="small muted">Узнайте заранее, хватит ли денег на счёте</div>
          </div>
        </div>
        <button type="button" className="btn btn-lime" disabled={busy} onClick={demo} style={{ padding: 14, fontSize: 16 }}>
          {busy ? 'Открываем…' : '▶ Посмотреть демо — без регистрации'}
        </button>
        <div className="tiny" style={{ textAlign: 'center', marginTop: -6 }}>
          ИТ-компания с крупным клиентом, который задерживает оплату. У вас будет своя копия — можно добавлять платежи и загружать выписку.
        </div>
        <div className="row tiny" style={{ gap: 8 }}><span style={{ flex: 1, height: 1, background: 'var(--border)' }} />или войдите<span style={{ flex: 1, height: 1, background: 'var(--border)' }} /></div>
        <label className="field">Логин
          <input className="input" value={username} onChange={(e) => setUsername(e.target.value)} autoComplete="username" required />
        </label>
        <label className="field">Пароль
          <input className="input" type="password" value={password} onChange={(e) => setPassword(e.target.value)} autoComplete="current-password" required />
        </label>
        {error && <div className="notice notice-err" role="alert">{error}</div>}
        <button className="btn" disabled={busy || !username || !password} style={{ padding: 12 }}>{busy ? 'Входим…' : 'Войти'}</button>
        <div className="tiny" style={{ textAlign: 'center' }}>
          🔒 Соединение защищено, данные выписки не попадают в логи.
          {USE_MOCK && <><br />Демо-режим: подойдёт любой логин и пароль.</>}
        </div>
      </form>
    </div>
  )
}
