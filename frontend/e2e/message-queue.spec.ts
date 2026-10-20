import { expect, test } from '@playwright/test'

test('native queue: add, restore, remove and resume on desktop and mobile', async ({ page }, testInfo) => {
  const state = {
    id: 'queue-chat', title: 'Подготовка API', busy: true,
    provider_id: 'local', model_id: 'demo', default_variant: 'none', variants: ['none'],
    tokens_used: 1240, context_limit: 32000, generation_started_at: Date.now() / 1000,
    queue_supported: true, queue_enabled: true, queue_ready: true, queue_paused: false,
    queue_limit: 10, active_environment: 'test_int', opencode_url: null,
    queue: [] as Array<{ id: string; message: string; environment: string; model_id: string; thinking: string }>,
    events: [{ sequence: 1, kind: 'user', timestamp: Date.now() / 1000,
      payload: { text: 'Найди API каталога и подготовь черновик изменений', thinking: 'none' } }],
  }
  let resumed = false
  await page.addInitScript(() => {
    window.localStorage.setItem('autodeploy.ai.session', 'queue-chat')
    window.localStorage.setItem('autodeploy.environment', 'test_int')
    class Stream { close() {} }
    Object.defineProperty(window, 'EventSource', { value: Stream })
  })
  await page.route('**/api/v1/opencode/status', (route) => route.fulfill({ json: { state: 'ready' } }))
  await page.route('**/api/v1/opencode/models', (route) => route.fulfill({ json: { items: [
    { provider_id: 'local', model_id: 'demo', model_name: 'Demo model', variants: ['none'] },
  ] } }))
  await page.route('**/api/v1/ai/**', async (route) => {
    const path = new URL(route.request().url()).pathname
    if (path.endsWith('/messages')) {
      state.queue.push({ id: `msg_${state.queue.length + 1}`, message: route.request().postDataJSON().message,
        environment: 'test_int', model_id: 'demo', thinking: 'none' })
      await route.fulfill({ status: 202, json: { queued: true, queue_id: state.queue.at(-1)!.id } })
    } else if (route.request().method() === 'DELETE') {
      state.queue = state.queue.filter((item) => !path.endsWith('/' + item.id))
      await route.fulfill({ json: state })
    } else if (path.endsWith('/queue/resume')) {
      resumed = true
      await route.fulfill({ status: 202, json: { job_id: 'native-observer' } })
    } else if (path.endsWith('/sessions')) {
      await route.fulfill({ json: { items: [{ ...state, updated_at: Date.now() / 1000 }] } })
    } else { await route.fulfill({ json: state }) }
  })
  await page.goto('/')
  const input = page.getByRole('textbox').first()
  await input.fill('После этого проверь доступные планы подписки')
  await input.press('Enter')
  const queue = page.getByRole('region', { name: 'Очередь сообщений' })
  await expect(queue).toContainText('После этого проверь доступные планы подписки')
  await input.fill('И сравни найденные варианты в таблице')
  await page.getByRole('button', { name: 'В очередь', exact: true }).click()
  await expect(queue.locator('li')).toHaveCount(2)
  await page.screenshot({ path: testInfo.outputPath('queue-desktop.png'), fullPage: true })
  await page.reload()
  await expect(queue.locator('li')).toHaveCount(2)
  await queue.getByRole('button', { name: 'Убрать сообщение 1 из очереди' }).click()
  await expect(queue.locator('li')).toHaveCount(1)
  state.busy = false
  state.queue_paused = true
  await page.reload()
  await expect(queue.getByRole('button', { name: 'Продолжить очередь' })).toBeEnabled()
  await page.setViewportSize({ width: 390, height: 844 })
  await queue.scrollIntoViewIfNeeded()
  await expect(queue).toBeVisible()
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true)
  await page.screenshot({ path: testInfo.outputPath('queue-mobile.png'), fullPage: true })
  await queue.getByRole('button', { name: 'Продолжить очередь' }).click()
  await expect.poll(() => resumed).toBe(true)
})
