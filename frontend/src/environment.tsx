import { createContext, ReactNode, useContext, useEffect, useMemo, useState } from 'react'
import type { Environment } from './types'

interface EnvironmentState {
  environments: Environment[]
  environment: string
  setEnvironment: (value: string) => void
  setEnvironments: (value: Environment[]) => void
}

const EnvironmentContext = createContext<EnvironmentState | null>(null)

export function EnvironmentProvider({ children }: { children: ReactNode }) {
  const [environments, setEnvironments] = useState<Environment[]>([])
  const [environment, setEnvironmentState] = useState(
    () => window.localStorage.getItem('autodeploy.environment') || 'test_int',
  )

  const setEnvironment = (value: string) => {
    setEnvironmentState(value)
    window.localStorage.setItem('autodeploy.environment', value)
  }

  useEffect(() => {
    if (environments.length && !environments.some((item) => item.key === environment)) {
      setEnvironment(environments[0].key)
    }
  }, [environment, environments])

  const value = useMemo(
    () => ({ environments, environment, setEnvironment, setEnvironments }),
    [environment, environments],
  )
  return <EnvironmentContext.Provider value={value}>{children}</EnvironmentContext.Provider>
}

export function useEnvironment() {
  const value = useContext(EnvironmentContext)
  if (!value) throw new Error('useEnvironment must be used inside EnvironmentProvider')
  return value
}
