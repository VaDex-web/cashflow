import { Navigate, Route, Routes } from 'react-router-dom'
import { Layout } from './components/Layout'
import { useSession } from './lib/session'
import { Dashboard } from './pages/Dashboard'
import { Login } from './pages/Login'
import { Upload } from './pages/Upload'
import { Scenarios } from './pages/Scenarios'
import { PlanFact } from './pages/PlanFact'
import { Events } from './pages/Events'
import { Operations } from './pages/Operations'
import { Quality } from './pages/Quality'

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
        <Route path="scenarios" element={<Scenarios />} />
        <Route path="plan-fact" element={<PlanFact />} />
        <Route path="events" element={<Events />} />
        <Route path="operations" element={<Operations />} />
        <Route path="quality" element={<Quality />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Route>
    </Routes>
  )
}
