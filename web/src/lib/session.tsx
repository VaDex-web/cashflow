import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from 'react'
import { auth } from '../api/client'

const COMPANY_KEY = 'cf_company'

function readCompany(): string | null {
  try { return localStorage.getItem(COMPANY_KEY) } catch { return null }
}

interface Session {
  token: string | null
  companyId: string | null
  login(token: string): void
  logout(): void
  setCompany(id: string | null): void
}

const Ctx = createContext<Session | null>(null)

export function SessionProvider({ children }: { children: ReactNode }) {
  const [token, setToken] = useState(auth.token)
  const [companyId, setCompanyId] = useState(readCompany)

  const login = useCallback((t: string) => { auth.set(t); setToken(t) }, [])
  const logout = useCallback(() => { auth.set(null); setToken(null) }, [])
  const setCompany = useCallback((id: string | null) => {
    try { id ? localStorage.setItem(COMPANY_KEY, id) : localStorage.removeItem(COMPANY_KEY) } catch {  }
    setCompanyId(id)
  }, [])

  useEffect(() => {
    const t = setInterval(() => { if (token && !auth.token) setToken(null) }, 2000)
    return () => clearInterval(t)
  }, [token])

  return <Ctx.Provider value={{ token, companyId, login, logout, setCompany }}>{children}</Ctx.Provider>
}

export function useSession(): Session {
  const s = useContext(Ctx)
  if (!s) throw new Error('SessionProvider missing')
  return s
}
