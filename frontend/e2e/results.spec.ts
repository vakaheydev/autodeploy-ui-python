import { expect, test } from '@playwright/test'
import { blockText, installResultFixture } from './fixtures/results.mjs'

for (const width of [1280, 390]) {
  test(`result scroll, clipboard and polling (${width}px)`, async ({ page, context }) => {
    await page.setViewportSize({ width, height: 900 })
    await context.grantPermissions(['clipboard-read', 'clipboard-write'])
    const { setPollMode } = await installResultFixture(page, { confirmed: width === 1280, reducedMotion: width === 390 })
    await page.goto('/forms/example.result')
    await page.getByRole('button', { name: /^Отправить$/ }).click()
    if (width === 1280) await page.getByRole('button', { name: 'Подтвердить и отправить' }).click()
    const result = page.locator('.result-card')
    await expect(result).toBeFocused()
    await expect.poll(() => result.evaluate(el => Math.round(el.getBoundingClientRect().top))).toBeGreaterThanOrEqual(0)
    await expect.poll(() => result.evaluate(el => Math.round(el.getBoundingClientRect().top))).toBeLessThan(200)
    expect(await page.evaluate(() => window.resultScrolls)).toEqual([{ behavior: width === 390 ? 'auto' : 'smooth', block: 'start' }])
    expect(await result.locator('pre').first().evaluate(el => parseFloat(getComputedStyle(el).fontSize))).toBeGreaterThanOrEqual(15)
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBeTruthy()

    await page.getByRole('button', { name: 'Скопировать блок Данные для передачи' }).click()
    await expect(page.locator('.result-copy-notice')).toHaveText(/Блок скопирован/)
    expect(await page.evaluate(() => navigator.clipboard.readText())).toBe(blockText)
    await page.getByRole('button', { name: 'Скопировать ссылку https://example.invalid/tasks/42?view=full&lang=ru', exact: true }).click()
    await expect(page.locator('.result-copy-notice')).toHaveText(/Ссылка скопирована/)
    expect(await page.evaluate(() => navigator.clipboard.readText())).toBe('https://example.invalid/tasks/42?view=full&lang=ru')
    expect(page.url()).toContain('/forms/example.result')

    setPollMode('updated')
    await expect(result).toContainText('Финальный результат')
    await expect(result).not.toContainText('Данные для передачи')
    setPollMode('stopped')
    await expect(result).not.toContainText('Статус обновляется автоматически')
    await expect(result).toContainText('Новый блок')
    expect(await page.evaluate(() => window.resultScrolls.length)).toBe(1)
  })
}
