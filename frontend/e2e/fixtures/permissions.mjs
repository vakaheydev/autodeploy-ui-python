import { installMarkdownFixture } from './markdown.mjs'

export async function installPermissionFixture(page, { expired = false, failFirst = false } = {}) {
  await installMarkdownFixture(page)
  await page.addInitScript(() => {
    window.EventSource = class {
      constructor() { window.permissionEvents = this }
      close() {}
    }
  })
  const replies = []
  const state = {
    id: 'markdown-chat', title: 'Разрешение инструмента', busy: true,
    provider_id: 'local', model_id: 'demo', variants: ['none'], default_variant: 'none',
    tokens_used: 1000, context_limit: 32000, generation_started_at: Date.now() / 1000,
    opencode_url: null, queue_supported: true, queue_enabled: true, queue_ready: true,
    queue: [], queue_paused: false, active_environment: 'test_int',
    events: [{ sequence: 1, kind: 'agent_event', timestamp: 1, payload: {
      kind: 'permission', permission_id: 'per_example', title: 'Требуется разрешение: example_read',
      detail: '{"resource": "example/page"}', permission_always: true,
      permission_scope: 'project', permission_resources: ['example/*'],
    } }],
  }
  await page.route('**/api/v1/ai/**', async route => {
    const path = new URL(route.request().url()).pathname
    if (path.endsWith('/permissions/per_example')) {
      const body = route.request().postDataJSON()
      replies.push(body)
      if (failFirst && replies.length === 1) {
        await route.fulfill({ status: 503, json: { detail: 'Сервер временно недоступен' } })
        return
      }
      const decision = expired ? 'expired' : body.always ? 'always' : body.allow ? 'once' : 'reject'
      await route.fulfill({ json: { accepted: !expired, decision } })
      return
    }
    if (path.endsWith('/sessions')) await route.fulfill({ json: { items: [{ ...state, updated_at: 1 }] } })
    else if (path.includes('/sessions/')) await route.fulfill({ json: state })
    else await route.fallback()
  })
  return { replies, state }
}
