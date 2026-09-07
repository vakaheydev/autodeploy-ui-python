import { expect, test } from '@playwright/test'

test('opens the bundled application and validates a Python form', async ({ page }) => {
  await page.goto('/')
  await expect(page.getByRole('heading', { name: 'Gravitee AutoDeploy' })).toBeVisible()
  await page.getByRole('link', { name: /Формы/ }).first().click()
  await expect(page.getByRole('heading', { name: 'Каталог форм' })).toBeVisible()
  await expect(page.getByText('Создание и первичная настройка нового API в Gravitee.')).toBeVisible()
  await expect(page.getByText(/требует подтверждения/)).toHaveCount(0)
  await page.getByRole('link', { name: /Создание АПИ/ }).click()
  await expect(page.getByRole('heading', { name: 'Создание АПИ' })).toBeVisible()
  await expect(page.getByText(/версия схемы/)).toHaveCount(0)
  await expect(page.getByText('Python runtime')).toHaveCount(0)

  const fields = page.locator('.fields-grid > .form-field')
  const firstField = await fields.nth(0).boundingBox()
  const secondField = await fields.nth(1).boundingBox()
  expect(firstField).not.toBeNull()
  expect(secondField).not.toBeNull()
  expect(secondField!.y).toBeGreaterThanOrEqual(firstField!.y + firstField!.height)
  expect(Math.abs(secondField!.x - firstField!.x)).toBeLessThanOrEqual(1)
  expect(Math.abs(secondField!.width - firstField!.width)).toBeLessThanOrEqual(1)

  await page.getByPlaceholder('Введите название АПИ').fill('Orders API')
  await page.getByPlaceholder('Имя команды или ответственного').fill('Payments Team')
  await page.getByRole('button', { name: 'Категория АПИ' }).click()
  await page.getByRole('option', { name: 'Внутреннее АПИ' }).click()
  await page.getByPlaceholder('/api/v1/my-service').fill('/orders/v1')
  await page.getByRole('button', { name: 'Тип эндпоинта' }).click()
  await page.getByRole('option', { name: 'REST' }).click()
  await page.getByRole('button', { name: /Просмотр JSON/ }).click()
  await expect(page.getByRole('dialog', { name: 'Предварительный просмотр' })).toContainText('Orders API')
  await expect(page.getByRole('dialog')).toContainText('/orders/v1')
})

test('renders on a narrow viewport without losing navigation', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 })
  await page.goto('/forms')
  await expect(page.getByRole('heading', { name: 'Каталог форм' })).toBeVisible()
  await expect(page.getByRole('navigation', { name: 'Основная навигация' })).toBeVisible()
})

test('searches APIs automatically after the user stops typing', async ({ page }) => {
  await page.goto('/search')
  await expect(page.getByRole('button', { name: 'TEST' })).toHaveAttribute('aria-pressed', 'true')
  await expect(page.getByRole('button', { name: 'INT' })).toHaveAttribute('aria-pressed', 'true')
  const response = page.waitForResponse((value) => (
    value.url().endsWith('/api/v1/search')
      && value.request().method() === 'POST'
  ))

  await page.getByPlaceholder('Название, context path или ID API').fill('service103')

  expect((await response).ok()).toBe(true)
  const result = page.locator('.search-result').filter({ hasText: 'service103' })
  await expect(result).toBeVisible()
  await result.click()
  await expect(page.getByRole('dialog', { name: /Карточка: service103/ })).toContainText('/api/v1/users/service103')
  await page.getByRole('dialog').getByRole('button', { name: 'Закрыть' }).click()

  await expect(page.getByRole('button', { name: /Обновить данные/ })).toBeVisible()
  await page.getByRole('button', { name: /Обновить данные/ }).click()
  const refreshDialog = page.getByRole('dialog', { name: 'Обновление данных поиска' })
  await expect(refreshDialog).toContainText('TEST INT')
  await expect(refreshDialog).toContainText(/Ещё не обновлялось|\d{4}/)
  const refreshed = page.waitForResponse((value) => (
    value.url().endsWith('/api/v1/search/refresh')
      && value.request().method() === 'POST'
  ))
  await refreshDialog.getByRole('button', { name: 'Обновить', exact: true }).click()
  expect((await refreshed).ok()).toBe(true)
  await expect(refreshDialog).not.toBeVisible()
})

test('searches a large API dictionary on the Python server', async ({ page }) => {
  await page.goto('/forms/other.ingress.enable')
  await expect(page.getByRole('heading', { name: 'Включение ингрессов' })).toBeVisible()
  await page.getByRole('button', { name: 'АПИ' }).click()
  const search = page.getByPlaceholder('Можно искать по: name, context_path, id').first()
  await expect(search).toBeVisible()

  const response = page.waitForResponse((value) => (
    value.url().includes('/fields/apis/options') && value.request().method() === 'POST'
  ))
  await search.fill('/api/v1/users/service103')
  await expect((await response).status()).toBe(200)
  const option = page.getByRole('option', { name: /service103/ })
  await expect(option).toBeAttached()
  await expect(option).toContainText('context_path: /api/v1/users/service103')
  await expect(option).toContainText('id: 550e8400-e29b-41d4-a716-446655440002')
  await option.click({ button: 'right' })
  const card = page.getByRole('dialog', { name: /Карточка: service103/ })
  await expect(card).toBeVisible()
  const copyContextPath = card.getByTitle('Скопировать context_path')
  await copyContextPath.click()
  await expect(copyContextPath).toHaveClass(/copied/)
})

test('uses dark surfaces and high-contrast form labels in the dark theme', async ({ page }) => {
  await page.goto('/forms/api.create')
  await page.getByRole('button', { name: 'Включить тёмную тему' }).click()

  const input = page.getByPlaceholder('Введите название АПИ')
  const label = page.locator('label[for="name"]')
  const secondaryButton = page.getByRole('button', { name: /Просмотр JSON/ })
  const select = page.getByRole('button', { name: 'Категория АПИ' })
  for (const control of [input, secondaryButton, select]) {
    await expect.poll(() => control.evaluate((element) => getComputedStyle(element).backgroundColor)).not.toBe('rgb(255, 255, 255)')
  }
  await expect.poll(() => label.evaluate((element) => getComputedStyle(element).color)).toBe('rgb(229, 237, 248)')
})

test('filters the catalog by Python field keywords and switches theme', async ({ page }) => {
  await page.goto('/forms')
  await page.getByRole('textbox', { name: 'Поиск форм' }).fill('Контекстный путь')
  await expect(page.getByRole('link', { name: /Создание АПИ/ })).toBeVisible()
  await expect(page.getByText(/найдено/)).toBeVisible()
  await page.getByRole('button', { name: 'Включить тёмную тему' }).click()
  await expect(page.locator('html')).toHaveAttribute('data-theme', 'dark')
  await page.getByRole('link', { name: /Настройки/ }).click()
  await expect(page.getByRole('heading', { name: 'Настройки' })).toBeVisible()
  await page.getByRole('button', { name: /Общие/ }).click()
  await page.getByRole('button', { name: 'Обзор' }).first().click()
  await expect(page.getByRole('dialog', { name: /Выберите папку/ })).toBeVisible()
  await page.getByRole('dialog').getByRole('button', { name: 'Закрыть' }).click()
  await page.getByRole('button', { name: /OpenCode/ }).click()
  await expect(page.getByRole('heading', { name: 'OpenCode Server', exact: true })).toBeVisible()
  await expect(page.getByText('Встроенный MCP Server')).toBeVisible()
  await expect(page.getByRole('navigation', { name: 'Основная навигация' }).getByRole('link', { name: 'OpenCode' })).toHaveCount(0)
})

test('redirects the legacy OpenCode route to its settings section', async ({ page }) => {
  await page.goto('/opencode')
  await expect(page).toHaveURL(/\/settings\?section=OpenCode$/)
  await expect(page.getByRole('heading', { name: 'Настройки' })).toBeVisible()
  await expect(page.getByRole('heading', { name: 'OpenCode Server', exact: true })).toBeVisible()
})

test('shows settings validation errors beside the affected field', async ({ page }) => {
  await page.route('**/api/v1/settings', async (route) => {
    if (route.request().method() === 'PUT') {
      await route.fulfill({
        status: 422,
        contentType: 'application/json',
        body: JSON.stringify({
          detail: { message: 'Порт веб-сервера: минимум 1', fields: ['AUTODEPLOY_PORT'] },
        }),
      })
      return
    }
    await route.continue()
  })
  await page.goto('/settings')
  await page.getByRole('button', { name: /Общие/ }).click()
  const port = page.getByLabel('Порт веб-сервера')
  await port.fill('0')
  await page.getByRole('button', { name: /Сохранить настройки/ }).click()

  const field = page.locator('[data-setting-key="AUTODEPLOY_PORT"]')
  await expect(field).toHaveClass(/invalid/)
  await expect(field.getByRole('alert')).toContainText('минимум 1')
  await expect(page.locator('.settings-page > .alert.error')).toHaveCount(0)
})

test('autosaves, restores and manually deletes a form draft', async ({ page }) => {
  await page.goto('/forms/api.create')
  await expect(page.getByRole('heading', { name: 'Создание АПИ' })).toBeVisible()
  const savedResponse = page.waitForResponse((response) => (
    response.url().includes('/api/v1/drafts/api.create')
      && response.request().method() === 'PUT'
      && response.status() === 200
  ))
  await page.getByPlaceholder('Введите название АПИ').fill('Persistent draft API')
  const saved = await (await savedResponse).json() as { id: string }
  await expect(page.getByText('черновик сохранён')).toBeVisible()
  await expect(page).toHaveURL(new RegExp(`draft=${saved.id}`))

  await page.reload()
  await expect(page.getByPlaceholder('Введите название АПИ')).toHaveValue('Persistent draft API')
  await page.getByRole('link', { name: /Каталог форм/ }).click()
  await page.getByRole('tab', { name: /Черновики/ }).click()
  const link = page.locator(`a[href="/forms/api.create?draft=${saved.id}"]`)
  await expect(link).toBeVisible()
  await link.locator('xpath=..').getByRole('button', { name: 'Удалить черновик Создание АПИ' }).click()
  await expect(link).toHaveCount(0)
})
