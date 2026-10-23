import { Navigate, Route, Routes } from 'react-router-dom'
import { Layout } from './components/Layout'
import { useSession } from './lib/session'
import { Dashboard } from './pages/Dashboard'
import { Login } from './pages/Login'
import { Upload } from './pages/Upload'

function Soon({ title }: { title: string }) {
  return <div className="card"><h2>{title}</h2><p className="muted" style={{ marginTop: 8 }}>Экран в работе.</p></div>
}

export default function App() {
  const { token } = useSession()
  if (!token) {
    return (
      <Routes>
        <Route path="*" element={<Login />} />
      </Routes>
    )
  }
  return (
    <Routes>
      <Route element={<Layout />}>
        <Route index element={<Dashboard />} />
        <Route path="upload" element={<Upload />} />
        <Route path="scenarios" element={<Soon title="Что если" />} />
        <Route path="plan-fact" element={<Soon title="План и факт" />} />
        <Route path="events" element={<Soon title="Платежи и источники" />} />
        <Route path="operations" element={<Soon title="Операции" />} />
        <Route path="quality" element={<Soon title="Качество прогноза" />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Route>
    </Routes>
  )
}
