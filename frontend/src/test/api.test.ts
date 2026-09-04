import { afterEach, describe, expect, it, vi } from 'vitest'
import { api } from '../api'

describe('api client', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('surfaces the safe server error message', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => new Response(
      JSON.stringify({ error: { code: 'bad', message: 'Проверьте данные' } }),
      { status: 422, headers: { 'content-type': 'application/json' } },
    )))
    await expect(api('/api/v1/test')).rejects.toMatchObject({ status: 422, message: 'Проверьте данные' })
  })
})
