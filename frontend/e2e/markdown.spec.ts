import { expect, test } from '@playwright/test'
import { installMarkdownFixture } from './fixtures/markdown.mjs'

test('Markdown tables and code scroll inside the chat on desktop and mobile', async ({ page }) => {
  await installMarkdownFixture(page)
  await page.goto('/')
  const table = page.getByRole('region', { name: 'Таблица в ответе Copilot' })
  await expect(table.getByRole('table')).toBeVisible()
  await expect(table.getByRole('columnheader')).toHaveCount(6)
  await expect(table.getByText('11111111-2222-4333-8444-555555555555')).toBeVisible()
  for (const width of [1280, 390]) {
    await page.setViewportSize({ width, height: 900 })
    await table.scrollIntoViewIfNeeded()
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBeTruthy()
    expect(await table.evaluate(element => element.scrollWidth > element.clientWidth)).toBeTruthy()
    await table.focus()
    await page.keyboard.press('ArrowRight')
    await expect.poll(() => table.evaluate(element => element.scrollLeft)).toBeGreaterThan(0)
    expect(await page.getByLabel('Блок кода').textContent()).toContain('  "contextPath": "/payments/v2"')
  }
})
