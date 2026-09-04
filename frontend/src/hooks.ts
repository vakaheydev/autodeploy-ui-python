import { DependencyList, useCallback, useEffect, useRef, useState } from 'react'

export function useAsync<T>(loader: (signal: AbortSignal) => Promise<T>, dependencies: DependencyList) {
  const [data, setData] = useState<T | null>(null)
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(true)
  const sequence = useRef(0)

  const reload = useCallback(() => {
    const controller = new AbortController()
    const current = ++sequence.current
    setLoading(true)
    setError('')
    loader(controller.signal)
      .then((value) => current === sequence.current && setData(value))
      .catch((reason: unknown) => {
        if (current !== sequence.current || controller.signal.aborted) return
        setError(reason instanceof Error ? reason.message : String(reason))
      })
      .finally(() => current === sequence.current && setLoading(false))
    return controller
  }, dependencies)

  useEffect(() => {
    const controller = reload()
    return () => controller.abort()
  }, [reload])

  return { data, error, loading, reload }
}
