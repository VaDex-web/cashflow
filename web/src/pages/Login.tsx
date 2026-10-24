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
      setError(
        err instanceof Error && 'status' in err && (err as { status: number }).status === 401
          ? 'Неверный логин или пароль'
          : err instanceof Error ? err.message : String(err),
      )
    } finally {
      setBusy(false)
    }
  }

  return (
    <div
      style={{
        minHeight: '100vh',
        display: 'grid',
        placeItems: 'center',
        padding: 24,
        background: 'radial-gradient(ellipse at top, #f0f7f0 0%, #f1f3f9 60%, #e4e7ec 100%)',
      }}
    >
      <div
        className="card"
        style={{
          width: 440,
          maxWidth: '100%',
          padding: '36px 32px',
          boxShadow: 'var(--shadow-hover)',
          borderRadius: 16,
        }}
      >
        <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', textAlign: 'center', marginBottom: 24 }}>
          <img src="/logo.svg" alt="Денежный прогноз" style={{ height: 42, width: 42, borderRadius: 10, marginBottom: 12 }} />
          <h1 style={{ fontSize: 22, fontWeight: 700, color: 'var(--text)', letterSpacing: '-0.02em' }}>
            Денежный прогноз
          </h1>
          <div className="small muted" style={{ marginTop: 4 }}>
            Система прогнозирования кассовых разрывов и ликвидности
          </div>
        </div>

        <button
          type="button"
          className="btn btn-lime"
          disabled={busy}
          onClick={demo}
          style={{ width: '100%', padding: '13px 18px', fontSize: 15, justifyContent: 'center', marginBottom: 6 }}
        >
          {busy ? 'Открываем…' : 'Посмотреть демо — без регистрации'}
        </button>

        <p className="tiny muted" style={{ textAlign: 'center', lineHeight: 1.45, marginBottom: 18 }}>
          Готовая модель ИТ-компании с кассовым разрывом. У вас будет отдельная копия с возможностью добавления платежей.
        </p>

        <div className="row tiny" style={{ gap: 10, margin: '8px 0 16px' }}>
          <span style={{ flex: 1, height: 1, background: 'var(--border)' }} />
          <span style={{ color: 'var(--text-3)', fontWeight: 500 }}>или войдите в аккаунт</span>
          <span style={{ flex: 1, height: 1, background: 'var(--border)' }} />
        </div>

        <form onSubmit={submit} style={{ display: 'grid', gap: 16 }}>
          <label className="field">
            <span>Логин или email</span>
            <input
              className="input"
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              autoComplete="username"
              placeholder="demo"
              required
            />
          </label>

          <label className="field">
            <span>Пароль</span>
            <input
              className="input"
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              autoComplete="current-password"
              placeholder="••••••••"
              required
            />
          </label>

          {error && (
            <div className="notice notice-err" role="alert" style={{ fontSize: 13, padding: '10px 12px', display: 'flex', alignItems: 'center', gap: 8 }}>
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" style={{ flexShrink: 0 }}>
                <circle cx="12" cy="12" r="10" />
                <line x1="12" y1="8" x2="12" y2="12" />
                <line x1="12" y1="16" x2="12.01" y2="16" />
              </svg>
              <span>{error}</span>
            </div>
          )}

          <button
            type="submit"
            className="btn btn-ghost"
            disabled={busy || !username || !password}
            style={{ width: '100%', padding: '12px 18px', justifyContent: 'center' }}
          >
            {busy ? 'Входим…' : 'Войти'}
          </button>
        </form>

        <div className="tiny muted" style={{ textAlign: 'center', marginTop: 20, display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 6 }}>
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <rect x="3" y="11" width="18" height="11" rx="2" ry="2" />
            <path d="M7 11V7a5 5 0 0 1 10 0v4" />
          </svg>
          <span>Соединение защищено · Конфиденциальность гарантирована</span>
        </div>

        {USE_MOCK && (
          <div className="tiny muted" style={{ textAlign: 'center', marginTop: 6, color: 'var(--primary-active)' }}>
            Демо-режим: доступен любой логин и пароль
          </div>
        )}
      </div>
    </div>
  )
}
