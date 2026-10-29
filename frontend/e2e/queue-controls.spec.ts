import { expect, test } from '@playwright/test'
import { installQueueControlsFixture } from './fixtures/queue-controls.mjs'

for (const width of [1440, 390]) {
  test(`queue controls and expanding composer (${width}px)`, async ({ page }) => {
    await page.setViewportSize({ width, height: 900 })
    const { calls } = await installQueueControlsFixture(page)
    await page.goto('/')
    const queue = page.getByRole('region', { name: 'Очередь сообщений' })
    await expect(queue.locator('li')).toHaveCount(3)
    await expect(queue).not.toContainText('Далее в диалоге')
    const box = await queue.boundingBox()
    const main = await page.locator('.copilot-main').boundingBox()
    if (width > 1100) expect(box!.x).toBeGreaterThanOrEqual(main!.x + main!.width)
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBeTruthy()
    await queue.getByRole('button', { name: 'Переместить сообщение 2 выше' }).click()
    await expect(queue.locator('li').first()).toContainText('Сравни окружения')
    await queue.getByRole('button', { name: 'Отправить сообщение 1 сейчас' }).click()
    await expect(queue.locator('li')).toHaveCount(2)
    expect(calls[0].body).toEqual({ message_ids: ['msg_1', 'msg_0', 'msg_2'] })
    expect(calls[1].path).toContain('/queue/msg_1/send')
    const input = page.locator('.chat-composer textarea')
    const initial = (await input.boundingBox())!.height
    await input.fill('Уточнение по задаче\n'.repeat(30))
    const expanded = (await input.boundingBox())!.height
    expect(expanded).toBeGreaterThan(initial)
    expect(expanded).toBeLessThanOrEqual(240)
    expect(await input.evaluate(el => el.scrollHeight > el.clientHeight)).toBeTruthy()
    await page.getByRole('button', { name: 'Отправить сейчас', exact: true }).click()
    await expect(input).toHaveValue('')
    expect((await input.boundingBox())!.height).toBe(initial)
    expect(calls.at(-1).body.delivery).toBe('steer')
  })
}
