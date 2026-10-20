import { installMarkdownFixture } from './markdown.mjs'

export async function installMCPFixture(page) {
  await installMarkdownFixture(page)
  const calls = []
  const tools = [
    { name: 'read_page', description: 'Получить страницу по её идентификатору.', policy: 'ask' },
    { name: 'update_page', description: 'Обновить страницу.', policy: 'deny' },
  ]
  await page.route('**/api/v1/settings**', route => {
    const path = new URL(route.request().url()).pathname
    return route.fulfill({ json: path.endsWith('/settings') ? { groups: [{ name: 'OpenCode', fields: [{
      key: 'OPENCODE_ALLOWED_MCP', label: 'Разрешённые MCP', group: 'OpenCode',
      kind: 'text', value: 'docs', default: '', configured: true, picker: 'mcp_multi',
      description: 'Серверы для Copilot', required: false, restart_required: false,
    }] }] } : { rules: [] } })
  })
  await page.route('**/api/v1/opencode/mcp**', async route => {
    const path = new URL(route.request().url()).pathname
    if (route.request().method() === 'POST') {
      calls.push({ path, body: route.request().postDataJSON() })
      if (path.endsWith('/policy')) tools.find(tool => path.includes(`/${tool.name}/`)).policy = route.request().postDataJSON().policy
      await route.fulfill({ json: { saved: true, restarted: true, applies: 'next_turn' } })
    } else await route.fulfill({ json: path.endsWith('/tools') ? { name: 'docs', tools, enabled: true }
      : { connected: true, items: [{ name: 'docs', status: 'connected', error: '' }] } })
  })
  return { calls }
}
