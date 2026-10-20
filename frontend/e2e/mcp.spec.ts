import { expect, test } from '@playwright/test'
import { installMCPFixture } from './fixtures/mcp.mjs'

test('MCP catalog, per-tool policies and restart work on a narrow screen', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 900 })
  const { calls } = await installMCPFixture(page)
  await page.goto('/settings?section=OpenCode')
  const server = page.getByRole('article', { name: 'MCP docs' })
  await server.getByText('Инструменты и разрешения').click()
  const policy = server.getByRole('combobox', { name: 'Разрешение docs / read_page' })
  await expect(policy).toHaveValue('ask')
  await policy.selectOption('allow')
  await expect(server.getByRole('status')).toContainText('Сохранено')
  await server.getByRole('button', { name: 'Перезапустить' }).click()
  await expect(server.getByRole('status')).toHaveText('Перезапуск выполнен')
  await expect(policy).toHaveValue('allow')
  expect(calls).toEqual([
    { path: '/api/v1/opencode/mcp/docs/tools/read_page/policy', body: { policy: 'allow' } },
    { path: '/api/v1/opencode/mcp/docs/restart', body: {} },
  ])
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBeTruthy()
})
