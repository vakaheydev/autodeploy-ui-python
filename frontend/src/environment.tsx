import { createContext, ReactNode, useCallback, useContext, useEffect, useMemo, useRef, useState } from 'react'
import { post } from './api'
import type { Environment } from './types'

interface EnvironmentState {
  environments: Environment[]
  environment: string
  environmentSwitching: boolean
  environmentError: string
  setEnvironment: (value: string) => Promise<boolean>
  setEnvironments: (value: Environment[]) => void
  dismissEnvironmentError: () => void
}

interface EnvironmentActivation {
  previous_environment: string | null
  environment: string
  changed: boolean
  hook_configured: boolean
}

const EnvironmentContext = createContext<EnvironmentState | null>(null)

export function EnvironmentProvider({ children }: { children: ReactNode }) {
  const [environments, setEnvironments] = useState<Environment[]>([])
  const [environment, setEnvironmentState] = useState(
    () => window.localStorage.getItem('autodeploy.environment') || 'test_int',
  )
  const [environmentSwitching, setEnvironmentSwitching] = useState(false)
  const [environmentError, setEnvironmentError] = useState('')
  const requestSequence = useRef(0)
  const switching = useRef(false)

  const dismissEnvironmentError = useCallback(() => setEnvironmentError(''), [])

  const setEnvironment = useCallback((value: string): Promise<boolean> => {
    const target = value.trim()
    if (!target || switching.current) return Promise.resolve(false)
    if (target === environment) return Promise.resolve(true)
    const previous = environments.some((item) => item.key === environment)
      ? environment
      : null
    const requestId = ++requestSequence.current
    switching.current = true
    setEnvironmentSwitching(true)
    setEnvironmentError('')
    return post<EnvironmentActivation>('/api/v1/environments/activate', {
      previous_environment: previous,
      environment: target,
    }).then((result) => {
      if (requestSequence.current !== requestId) return false
      setEnvironmentState(result.environment)
      window.localStorage.setItem('autodeploy.environment', result.environment)
      return true
    }).catch((reason: unknown) => {
      if (requestSequence.current !== requestId) return false
      setEnvironmentError(reason instanceof Error ? reason.message : String(reason))
      return false
    }).finally(() => {
      if (requestSequence.current !== requestId) return
      switching.current = false
      setEnvironmentSwitching(false)
    })
  }, [environment, environments])

  useEffect(() => {
    if (environments.length && !environments.some((item) => item.key === environment)) {
      void setEnvironment(environments[0].key)
    }
  }, [environment, environments, setEnvironment])

  const value = useMemo(
    () => ({
      environments,
      environment,
      environmentSwitching,
      environmentError,
      setEnvironment,
      setEnvironments,
      dismissEnvironmentError,
    }),
    [dismissEnvironmentError, environment, environmentError, environmentSwitching, environments, setEnvironment],
  )
  return <EnvironmentContext.Provider value={value}>{children}</EnvironmentContext.Provider>
}

export function useEnvironment() {
  const value = useContext(EnvironmentContext)
  if (!value) throw new Error('useEnvironment must be used inside EnvironmentProvider')
  return value
}
