import { describe, expect, it } from 'vitest'
import { restorePath, setPathValue } from '../pages/FormPage'

describe('inline AI review values', () => {
  it('accepts a nested proposal without mutating the previous form state', () => {
    const current = { name: 'Old', proxy: { host: 'old.local', port: 8080 } }
    const accepted = setPathValue(current, 'proxy.host', 'new.local')
    expect(accepted).toEqual({ name: 'Old', proxy: { host: 'new.local', port: 8080 } })
    expect(current.proxy.host).toBe('old.local')
  })

  it('rejects a proposal by restoring or deleting its baseline value', () => {
    expect(restorePath({ name: 'AI' }, { name: 'Manual' }, 'name')).toEqual({ name: 'Manual' })
    expect(restorePath({ name: 'AI', extra: 'AI only' }, { name: 'Manual' }, 'extra')).toEqual({ name: 'AI' })
  })
})
