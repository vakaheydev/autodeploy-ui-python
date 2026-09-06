import { useEffect } from 'react'
import { Navigate, Route, Routes } from 'react-router-dom'
import { api } from './api'
import { Shell } from './components/Shell'
import { EnvironmentProvider, useEnvironment } from './environment'
import { FormPage } from './pages/FormPage'
import { FormsPage } from './pages/FormsPage'
import { HomePage } from './pages/HomePage'
import { RunsPage } from './pages/RunsPage'
import { SearchPage } from './pages/SearchPage'
import { SettingsPage } from './pages/SettingsPage'
import type { Category, Environment } from './types'

function RoutesWithBootstrap() {
  const { setEnvironments } = useEnvironment()
  useEffect(() => {
    api<{ categories: Category[]; environments: Environment[] }>('/api/v1/catalog')
      .then((value) => setEnvironments(value.environments))
      .catch(() => undefined)
  }, [setEnvironments])
  return (
    <Routes>
      <Route element={<Shell />}>
        <Route index element={<HomePage />} />
        <Route path="forms" element={<FormsPage />} />
        <Route path="forms/:formId" element={<FormPage />} />
        <Route path="search" element={<SearchPage />} />
        <Route path="runs" element={<RunsPage />} />
        <Route path="opencode" element={<Navigate to="/settings?section=OpenCode" replace />} />
        <Route path="settings" element={<SettingsPage />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Route>
    </Routes>
  )
}

export function App() {
  return <EnvironmentProvider><RoutesWithBootstrap /></EnvironmentProvider>
}
