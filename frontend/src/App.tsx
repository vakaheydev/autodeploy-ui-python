import { lazy, useEffect } from 'react'
import { Navigate, Route, Routes } from 'react-router-dom'
import { api } from './api'
import { Shell } from './components/Shell'
import { EnvironmentProvider, useEnvironment } from './environment'
import type { Category, Environment } from './types'

const FormPage = lazy(() => import('./pages/FormPage').then((module) => ({ default: module.FormPage })))
const FormsPage = lazy(() => import('./pages/FormsPage').then((module) => ({ default: module.FormsPage })))
const HomePage = lazy(() => import('./pages/HomePage').then((module) => ({ default: module.HomePage })))
const RunsPage = lazy(() => import('./pages/RunsPage').then((module) => ({ default: module.RunsPage })))
const SearchPage = lazy(() => import('./pages/SearchPage').then((module) => ({ default: module.SearchPage })))
const SettingsPage = lazy(() => import('./pages/SettingsPage').then((module) => ({ default: module.SettingsPage })))
const TicketPage = lazy(() => import('./pages/TicketPage').then((module) => ({ default: module.TicketPage })))
const TicketsPage = lazy(() => import('./pages/TicketsPage').then((module) => ({ default: module.TicketsPage })))
const PluginPage = lazy(() => import('./pages/PluginPage').then((module) => ({ default: module.PluginPage })))
const PluginsPage = lazy(() => import('./pages/PluginsPage').then((module) => ({ default: module.PluginsPage })))

function RoutesWithBootstrap() {
  const { setEnvironments } = useEnvironment()
  useEffect(() => {
    api<{ categories: Category[]; environments: Environment[] }>('/api/v1/catalog')
      .then((value) => setEnvironments(value.environments))
      .catch(() => undefined)
  }, [setEnvironments])
  return <Routes>
      <Route element={<Shell />}>
        <Route index element={<HomePage />} />
        <Route path="forms" element={<FormsPage />} />
        <Route path="forms/:formId" element={<FormPage />} />
        <Route path="plugins" element={<PluginsPage />} />
        <Route path="plugins/:pluginId" element={<PluginPage />} />
        <Route path="search" element={<SearchPage />} />
        <Route path="tickets" element={<TicketsPage />} />
        <Route path="tickets/:ticketId" element={<TicketPage />} />
        <Route path="runs" element={<RunsPage />} />
        <Route path="opencode" element={<Navigate to="/settings?section=OpenCode" replace />} />
        <Route path="settings" element={<SettingsPage />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Route>
    </Routes>
}

export function App() {
  return <EnvironmentProvider><RoutesWithBootstrap /></EnvironmentProvider>
}
