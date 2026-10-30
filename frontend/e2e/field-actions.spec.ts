import { expect, test } from '@playwright/test'
import { exerciseFieldActions } from './fixtures/field-actions.mjs'

for (const width of [1440, 390]) {
  test(`field button updates its repeated owner from a remote reference (${width}px)`, async ({ page }) => {
    await page.setViewportSize({ width, height: 900 })
    await exerciseFieldActions(page, expect)
  })
}
