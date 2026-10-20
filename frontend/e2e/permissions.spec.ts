import { expect, test } from '@playwright/test'
import { installPermissionFixture } from './fixtures/permissions.mjs'

for (const [label, allow, always, status] of [
  ['Отклонить', false, false, 'Отклонено'],
  ['Разрешить один раз', true, false, 'Разрешено один раз'],
  ['Разрешать всегда', true, true, 'Постоянное разрешение сохранено в OpenCode'],
] as const) {
  test(`permission: ${label}`, async ({ page }) => {
    const { replies } = await installPermissionFixture(page)
    await page.goto('/')
    const card = page.getByRole('region', { name: 'Разрешение инструмента' })
    await expect(card.getByText(/включая следующие сессии/)).toBeVisible()
    await expect(page.getByRole('region', { name: 'Очередь сообщений' })).toHaveCount(0)
    await card.getByRole('button', { name: label, exact: true }).click()
    await expect(card.getByRole('status')).toHaveText(status)
    await expect(card.getByRole('button')).toHaveCount(0)
    expect(replies).toEqual([{ allow, always }])
  })
}

test('mobile permission reply can retry and closes an expired request', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 900 })
  const { replies } = await installPermissionFixture(page, { expired: true, failFirst: true })
  await page.goto('/')
  const card = page.getByRole('region', { name: 'Разрешение инструмента' })
  await card.getByRole('button', { name: 'Разрешить один раз' }).click()
  await expect(card.getByRole('alert')).toHaveText('Сервер временно недоступен')
  await card.getByRole('button', { name: 'Разрешить один раз' }).click()
  await expect(card.getByRole('status')).toHaveText('Запрос больше не ожидает ответа')
  expect(replies).toHaveLength(2)
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBeTruthy()
})
