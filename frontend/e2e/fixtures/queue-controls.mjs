import { installMarkdownFixture } from './markdown.mjs'

export async function installQueueControlsFixture(page) {
  await installMarkdownFixture(page)
  const state = {
    id: 'markdown-chat', title: 'Задачи API', busy: true, provider_id: 'local', model_id: 'demo',
    default_variant: 'none', variants: ['none'], tokens_used: 2000, context_limit: 32000,
    generation_started_at: Date.now() / 1000, opencode_url: null,
    queue_supported: true, queue_enabled: true, queue_ready: true, queue_paused: false,
    queue_limit: 10, active_environment: 'test_int',
    queue: ['Проверь планы подписки', 'Сравни окружения', 'Подготовь отчёт'].map((message, i) => ({
      id: `msg_${i}`, message, environment: 'test_int', model_id: 'demo', thinking: 'none',
    })),
    events: [{ sequence: 1, kind: 'user', timestamp: 1, payload: { text: 'Найди API платежей', thinking: 'none' } }],
  }
  const calls = []
  await page.route('**/api/v1/ai/**', async route => {
    const path = new URL(route.request().url()).pathname
    if (route.request().method() === 'POST') calls.push({ path, body: route.request().postDataJSON() })
    if (path.endsWith('/queue/reorder')) {
      state.queue = route.request().postDataJSON().message_ids.map(id => state.queue.find(item => item.id === id))
    } else if (path.endsWith('/send') || route.request().method() === 'DELETE') {
      state.queue = state.queue.filter(item => !path.includes(`/queue/${item.id}`))
    } else if (path.endsWith('/messages')) {
      await route.fulfill({ status: 202, json: { queued: true, queue_id: 'msg_immediate' } })
      return
    }
    await route.fulfill({ json: path.endsWith('/sessions') ? { items: [{ ...state, updated_at: 1 }] } : state })
  })
  return { state, calls }
}
