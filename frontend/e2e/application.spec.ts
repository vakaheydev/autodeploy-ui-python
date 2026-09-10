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

test('renders a Python-owned action dialog and applies its result', async ({ page }) => {
  const actionId = 'e2e-swagger-methods'
  const dialog = {
    success: true,
    id: actionId,
    title: 'Выбор методов Swagger',
    description: 'Поля и кнопки этого окна принадлежат Python-контракту.',
    form_version: '',
    values: { source: 'file', swagger_file: '{"openapi":"3.0.0"}', methods: [] },
    fields: [
      {
        key: 'source', path: 'source', label: 'Источник', type: 'text',
        required: true, visible: true, dynamic: false, placeholder: '',
        default: '', hint: '', file_type: '', width: 1, plural: false,
        plural_max: null, depends_on: null, depends_on_field: null,
        reference_dependencies: [],
      },
      {
        key: 'swagger_file', path: 'swagger_file', label: 'Swagger-файл', type: 'file',
        required: true, visible: true, dynamic: false, placeholder: '',
        default: '', hint: '', file_type: '.json', width: 1, plural: false,
        plural_max: null, depends_on: null, depends_on_field: null,
        reference_dependencies: [],
      },
      {
        key: 'methods', path: 'methods', label: 'Методы', type: 'multiselect',
        required: true, visible: true, dynamic: false, placeholder: '',
        default: [], hint: '', file_type: '', width: 1, plural: false,
        plural_max: null, depends_on: null, depends_on_field: null,
        reference_dependencies: [
          { field: 'source', parameter: 'source', item_field: null },
          { field: 'swagger_file', parameter: 'document', item_field: null },
        ],
        reference: {
          source: 'corp_swagger', resource: 'swagger_methods', value_key: 'id',
          label_key: 'name', search_keys: ['name', 'path'], detail_keys: ['path'],
          required_params: ['source', 'document'],
          endpoint: `/api/v1/forms/api.create/actions/${actionId}/dialog/fields/methods/options`,
        },
      },
    ],
    actions: [{
      id: 'apply', label: 'Применить методы', style: 'primary',
      confirmation_required: false, requires_valid_dialog: true,
      close_on_success: true,
    }],
  }
  let version = ''
  await page.route('**/api/v1/forms/api.create?environment=*', async (route) => {
    const response = await route.fetch()
    const body = await response.json()
    version = body.version
    await route.fulfill({
      response,
      json: {
        ...body,
        custom_actions: [...body.custom_actions, {
          id: actionId,
          label: 'Выбрать методы из Swagger',
          available: true,
          reason: '',
          style: 'Secondary',
          confirmation_required: false,
          dialog: true,
        }],
      },
    })
  })
  await page.route(`**/actions/${actionId}/dialog/fields/methods/options`, async (route) => {
    const body = route.request().postDataJSON()
    expect(body.dialog_values.swagger_file).toBe('{"openapi":"3.0.0"}')
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        items: [{ id: 'GET /orders', name: 'GET /orders', path: '/orders' }],
        total: 1,
        offset: 0,
        limit: 500,
        has_more: false,
      }),
    })
  })
  await page.route(`**/actions/${actionId}/dialog/state`, (route) => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify({ ...dialog, form_version: version }),
  }))
  await page.route(`**/actions/${actionId}/dialog/actions/apply`, async (route) => {
    const body = route.request().postDataJSON()
    expect(body.dialog_values.methods).toEqual(['GET /orders'])
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        ...dialog,
        form_version: version,
        values: body.dialog_values,
        form_values: { name: 'API with Swagger methods' },
        message: 'Методы перенесены',
        close_dialog: true,
      }),
    })
  })
  await page.route(`**/actions/${actionId}/dialog`, (route) => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify({ ...dialog, form_version: version }),
  }))

  await page.goto('/forms/api.create')
  await page.getByRole('button', { name: 'Выбрать методы из Swagger' }).click()
  const modal = page.getByRole('dialog', { name: 'Выбор методов Swagger' })
  await expect(modal).toContainText('Поля и кнопки этого окна принадлежат Python-контракту.')
  await modal.getByRole('checkbox', { name: 'GET /orders' }).check()
  await modal.getByRole('button', { name: 'Применить методы' }).click()

  await expect(modal).toHaveCount(0)
  await expect(page.getByPlaceholder('Введите название АПИ')).toHaveValue('API with Swagger methods')
})

test('renders on a narrow viewport without losing navigation', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 })
  await page.goto('/forms')
  await expect(page.getByRole('heading', { name: 'Каталог форм' })).toBeVisible()
  await expect(page.getByRole('navigation', { name: 'Основная навигация' })).toBeVisible()
})

test('commits an environment only after server activation succeeds', async ({ page }) => {
  await page.goto('/')
  const selector = page.getByRole('button', { name: 'Окружение' })
  await expect(selector).toContainText('Test Internal')

  const activation = page.waitForRequest((request) => (
    request.url().endsWith('/api/v1/environments/activate')
      && request.method() === 'POST'
  ))
  await selector.click()
  await page.getByRole('option', { name: 'Prod Internal' }).click()

  expect((await activation).postDataJSON()).toEqual({
    previous_environment: 'test_int',
    environment: 'prod_int',
  })
  await expect(selector).toContainText('Prod Internal')
})

test('shows a corporate environment rejection beside the selector', async ({ page }) => {
  await page.route('**/api/v1/environments/activate', (route) => route.fulfill({
    status: 422,
    contentType: 'application/json',
    body: JSON.stringify({ detail: { message: 'Контур временно недоступен' } }),
  }))
  await page.goto('/')
  const selector = page.getByRole('button', { name: 'Окружение' })

  await selector.click()
  await page.getByRole('option', { name: 'Prod Internal' }).click()

  await expect(page.getByRole('alert')).toContainText('Контур временно недоступен')
  await expect(selector).toContainText('Test Internal')
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
  await expect(result.locator('.search-result-title')).toContainText('TEST INT')
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
  await page.route('**/api/v1/drafts', (route) => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify({ items: [] }),
  }))
  await page.goto('/forms/api.create')
  await expect(page.locator('html')).toHaveAttribute('data-theme', 'dark')

  const input = page.getByPlaceholder('Введите название АПИ')
  const label = page.locator('label[for="name"]')
  const secondaryButton = page.getByRole('button', { name: /Просмотр JSON/ })
  const select = page.getByRole('button', { name: 'Категория АПИ' })
  for (const control of [input, secondaryButton, select]) {
    await expect.poll(() => control.evaluate((element) => getComputedStyle(element).backgroundColor)).not.toBe('rgb(255, 255, 255)')
  }
  await expect.poll(() => label.evaluate((element) => getComputedStyle(element).color)).toBe('rgb(229, 237, 248)')

  await page.goto('/forms')
  await page.getByRole('tab', { name: /Черновики/ }).click()
  const emptyDrafts = page.locator('.empty-state')
  await expect(emptyDrafts).toContainText('Черновиков пока нет')
  await expect.poll(() => emptyDrafts.evaluate((element) => getComputedStyle(element).backgroundImage)).toContain('rgb(16, 26, 42)')
})

test('filters the catalog by Python field keywords and switches theme', async ({ page }) => {
  await page.goto('/forms')
  await page.getByRole('textbox', { name: 'Поиск форм' }).fill('Контекстный путь')
  await expect(page.getByRole('link', { name: /Создание АПИ/ })).toBeVisible()
  await expect(page.getByText(/найдено/)).toBeVisible()
  await expect(page.locator('html')).toHaveAttribute('data-theme', 'dark')
  await page.getByRole('button', { name: 'Включить светлую тему' }).click()
  await expect(page.locator('html')).toHaveAttribute('data-theme', 'light')
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

test('shows submit progress and server failures inside the submit dialog', async ({ page }) => {
  let previewCalls = 0
  const submitTokens: string[] = []
  await page.route('**/api/v1/forms/api.create/preview', async (route) => {
    previewCalls += 1
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        valid: true,
        values: {},
        errors: [],
        visible_fields: [],
        payload: { operation: 'create-api' },
        confirmation_required: true,
        confirmation_text: 'Создать API?',
        confirmation_token: `confirmation-${previewCalls}`,
      }),
    })
  })
  await page.route('**/api/v1/forms/api.create/submit', async (route) => {
    const body = route.request().postDataJSON() as { confirmation_token: string }
    submitTokens.push(body.confirmation_token)
    if (submitTokens.length === 1) {
      await new Promise((resolve) => setTimeout(resolve, 350))
      await route.fulfill({
        status: 422,
        contentType: 'application/json',
        body: JSON.stringify({ detail: { message: 'TFS вернул 401 Unauthorized' } }),
      })
      return
    }
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        success: true,
        message: 'API создан',
        submission_id: 'submission-1',
        status: 'success',
        title: 'Создание API',
        content: 'Готово',
        response: {},
        payload: {},
        polling: false,
        poll_interval_ms: null,
      }),
    })
  })

  await page.goto('/forms/api.create')
  await page.getByRole('button', { name: 'Отправить', exact: true }).click()
  const dialog = page.getByRole('dialog', { name: 'Подтвердите операцию' })
  await expect(dialog).toBeVisible()
  await dialog.getByRole('button', { name: 'Подтвердить и отправить' }).click()

  await expect(dialog.getByRole('status')).toContainText('Отправляю форму')
  await expect(dialog.getByRole('button', { name: 'Отправляю…' })).toBeDisabled()
  await expect(dialog.locator('footer').getByRole('button', { name: 'Закрыть' })).toBeDisabled()

  await expect(dialog.getByRole('alert')).toContainText('TFS вернул 401 Unauthorized')
  await expect(dialog.getByRole('button', { name: 'Повторить отправку' })).toBeEnabled()
  expect(submitTokens).toEqual(['confirmation-2'])

  await dialog.getByRole('button', { name: 'Повторить отправку' }).click()
  await expect(dialog).not.toBeVisible()
  await expect(page.getByText('API создан')).toBeVisible()
  expect(submitTokens).toEqual(['confirmation-2', 'confirmation-3'])
})

test('renders a corporate plugin page and confirms its Python operation', async ({ page }) => {
  await page.route('**/api/v1/plugins', (route) => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify({
      items: [{
        id: 'reports.capacity',
        title: 'Нагрузка API',
        description: 'Корпоративный отчёт по нагрузке.',
        category: 'Отчёты',
        icon: 'puzzle',
        keywords: ['rps', 'capacity'],
        operation_count: 1,
      }],
    }),
  }))
  await page.route('**/api/v1/plugins/reports.capacity?environment=*', (route) => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify({
      id: 'reports.capacity',
      title: 'Нагрузка API',
      description: 'Корпоративный отчёт по нагрузке.',
      category: 'Отчёты',
      icon: 'puzzle',
      version: 'plugin-version-1',
      fields: [{
        key: 'api',
        path: 'api',
        label: 'API',
        type: 'select',
        required: true,
        visible: true,
        reference: {
          value_key: 'id',
          label_key: 'name',
          search_keys: ['context_path', 'name'],
          detail_keys: ['id', 'name', 'context_path'],
          required_params: [],
          endpoint: '/api/v1/plugins/reports.capacity/fields/api/options',
        },
      }],
      initial_values: {},
      operations: [{
        id: 'refresh',
        label: 'Обновить данные',
        description: 'Перестроить отчёт.',
        style: 'primary',
        confirmation_required: true,
        requires_valid_fields: true,
      }],
      widgets: [{ id: 'hint', kind: 'text', text: 'Выберите API', tone: 'info' }],
    }),
  }))
  await page.route('**/api/v1/plugins/reports.capacity/fields/api/options', (route) => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify({
      items: [{ id: 'api-1', name: 'Orders API', context_path: '/orders' }],
      total: 1,
      offset: 0,
      limit: 100,
      has_more: false,
    }),
  }))
  await page.route('**/api/v1/plugins/reports.capacity/state', (route) => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify({
      id: 'reports.capacity',
      title: 'Нагрузка API',
      description: 'Корпоративный отчёт по нагрузке.',
      category: 'Отчёты',
      icon: 'puzzle',
      version: 'plugin-version-1',
      initial_values: { api: 'api-1' },
      fields: [],
      operations: [{ id: 'refresh', label: 'Обновить данные', style: 'primary' }],
      widgets: [{ id: 'rps', kind: 'metric', label: 'Текущий RPS', value: 42 }],
    }),
  }))
  await page.route('**/api/v1/plugins/reports.capacity/operations/refresh', async (route) => {
    const body = route.request().postDataJSON() as { confirmation_token?: string }
    if (!body.confirmation_token) {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          success: false,
          confirmation_required: true,
          confirmation_text: 'Обновить корпоративные данные?',
          confirmation_token: 'confirm-plugin',
        }),
      })
      return
    }
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        success: true,
        message: 'Данные обновлены',
        values: { api: 'api-1' },
        widgets: [{ id: 'rps', kind: 'metric', label: 'Текущий RPS', value: 84 }],
        validation: { valid: true, values: { api: 'api-1' }, errors: [], visible_fields: ['api'] },
      }),
    })
  })

  await page.goto('/plugins')
  await expect(page.getByRole('heading', { name: 'Плагины' })).toBeVisible()
  await page.getByRole('link', { name: /Нагрузка API/ }).click()
  await expect(page.getByRole('heading', { name: 'Нагрузка API' })).toBeVisible()
  await page.getByRole('button', { name: 'API' }).click()
  await page.getByRole('option', { name: /Orders API/ }).click()
  await expect(page.getByText('Текущий RPS')).toBeVisible()
  await page.getByRole('button', { name: 'Обновить данные' }).click()
  const confirmation = page.getByRole('dialog', { name: 'Подтвердите операцию' })
  await expect(confirmation).toContainText('Обновить корпоративные данные?')
  await confirmation.getByRole('button', { name: 'Выполнить' }).click()
  await expect(page.getByText('Данные обновлены')).toBeVisible()
  await expect(page.locator('.plugin-metric')).toContainText('84')
})
