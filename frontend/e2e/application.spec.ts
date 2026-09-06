import { expect, test } from '@playwright/test'

test('opens the bundled application and validates a Python form', async ({ page }) => {
  await page.goto('/')
  await expect(page.getByRole('heading', { name: 'Gravitee AutoDeploy' })).toBeVisible()
  await page.getByRole('link', { name: /Формы/ }).first().click()
  await expect(page.getByRole('heading', { name: 'Каталог форм' })).toBeVisible()
  await page.getByRole('link', { name: /Создание АПИ/ }).click()
  await expect(page.getByRole('heading', { name: 'Создание АПИ' })).toBeVisible()

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

test('searches a large API dictionary on the Python server', async ({ page }) => {
  await page.goto('/forms/other.ingress.enable')
  await expect(page.getByRole('heading', { name: 'Включение ингрессов' })).toBeVisible()
  await page.getByRole('button', { name: 'АПИ' }).click()
  const search = page.getByPlaceholder('Найти: name, context_path').first()
  await expect(search).toBeVisible()

  const response = page.waitForResponse((value) => (
    value.url().includes('/fields/apis/options') && value.request().method() === 'POST'
  ))
  await search.fill('/api/v1/users/service103')
  await expect((await response).status()).toBe(200)
  await expect(page.getByRole('option', { name: /service103/ })).toBeAttached()
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
  await expect(page.getByText('Встроенный MCP Server')).toBeVisible()
})
