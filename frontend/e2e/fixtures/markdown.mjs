export const markdown = [
  '## prod_int (prod / int)',
  '',
  '| Название | ID | Версия | Статус | Virtual host | Файл |',
  '| --- | --- | --- | --- | --- | --- |',
  '| Example API | 11111111-2222-4333-8444-555555555555 | 1.0 | PUBLISHED | `api.example.test/payments/v2` | `INT/Apis/FullApis/services/example.FullAPI.json` |',
  '| Example Events | 66666666-7777-4888-8999-000000000000 | 2.0 | PUBLISHED | `api.example.test/events` | `INT/Apis/FullApis/services/example-events.FullAPI.json` |',
  '',
  '**Примечания:**',
  '',
  '- Контекстные пути сохраняются полностью: `/payments/v2`.',
  '- Идентификаторы отличаются между окружениями.',
  '',
  '> Изменения можно проверить перед отправкой.',
  '',
  '### Пример конфигурации',
  '',
  '```json',
  '{',
  '  "contextPath": "/payments/v2",',
  '  "description": "' + 'example-'.repeat(18) + '"',
  '}',
  '```',
  '',
  'Нужен полный JSON или сравнение вариантов?',
].join('\n')

export async function installMarkdownFixture(page) {
  await page.addInitScript(() => {
    localStorage.setItem('autodeploy.ai.session', 'markdown-chat')
    localStorage.setItem('autodeploy.environment', 'test_int')
    window.EventSource = class { close() {} }
  })
  const state = {
    id: 'markdown-chat', title: 'Сравнение API', busy: false,
    provider_id: 'local', model_id: 'demo', variants: ['none'], default_variant: 'none',
    tokens_used: 1200, context_limit: 32000, generation_started_at: null, opencode_url: null,
    queue_supported: true, queue_enabled: true, queue: [],
    events: [{ sequence: 1, kind: 'assistant', timestamp: 1,
      payload: { text: markdown, thinking: 'none' } }],
  }
  await page.route('**/api/**', async route => {
    const path = new URL(route.request().url()).pathname
    let result = { items: [] }
    if (path.endsWith('/opencode/status')) result = { state: 'ready', auth_required: false }
    else if (path.endsWith('/opencode/models')) result = {
      items: [{ provider_id: 'local', model_id: 'demo', model_name: 'Demo', variants: ['none'] }],
    }
    else if (path.endsWith('/catalog')) result = {
      categories: [], environments: [{ key: 'test_int', label: 'Test Internal' }],
    }
    else if (path.endsWith('/sessions')) result = { items: [{ ...state, updated_at: 1 }] }
    else if (path.includes('/sessions/')) result = state
    await route.fulfill({ json: result })
  })
}
