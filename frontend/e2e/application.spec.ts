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
  await page.getByLabel('Категория АПИ*').selectOption('internal')
  await page.getByPlaceholder('/api/v1/my-service').fill('/orders/v1')
  await page.getByLabel('Тип эндпоинта*').selectOption('rest')
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
  const search = page.getByPlaceholder('Поиск…').first()
  await expect(search).toBeVisible()

  const response = page.waitForResponse((value) => (
    value.url().includes('/fields/apis/options') && value.request().method() === 'POST'
  ))
  await search.fill('/api/v1/users/service103')
  await expect((await response).status()).toBe(200)
  await expect(page.getByRole('option', { name: 'service103' })).toBeAttached()
})
