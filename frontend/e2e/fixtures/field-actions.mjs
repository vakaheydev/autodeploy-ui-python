import { installMarkdownFixture } from './markdown.mjs'

export async function exerciseFieldActions(page, expect, url = '/') {
  await installMarkdownFixture(page)
  const calls = []
  const field = {
    key: 'target', path: 'target', label: 'Описание', type: 'textarea', required: false,
    visible: true, dynamic: false, placeholder: '', default: '', hint: '', width: 1,
    plural: true, plural_max: null, depends_on: null, depends_on_field: null,
    actions: [{ id: 'choose', label: 'Выбрать из справочника', style: 'Secondary', dialog: true }],
  }
  const form = {
    id: 'field-example', title: 'Кнопки полей', category: 'other', category_label: 'Прочее',
    version: 'v1', confirm_submit: false, itsm_support: false, http_method: 'POST',
    fields: [field], initial_values: { target: 'Первое описание', target_2: 'Второе описание' }, custom_actions: [],
  }
  const items = [{ id: 'a', name: 'Категория Alpha' }, { id: 'b', name: 'Категория Beta' }]
  const dialog = {
    success: true, id: 'choose', owner_field_path: 'target_2', title: 'Выбор категорий',
    description: 'Выберите категории для заполнения описания.', form_version: 'v1', values: { choices: [] },
    fields: [{ ...field, key: 'choices', path: 'choices', label: 'Категории', type: 'multiselect',
      plural: false, actions: [], reference: { source: 'http', resource: 'categories', value_key: 'id',
        label_key: 'name', search_keys: ['name'], detail_keys: [], required_params: [],
        endpoint: '/api/v1/forms/field-example/actions/choose/dialog/fields/choices/options' },
    }],
    actions: [{ id: 'apply', label: 'Заполнить поле', style: 'primary', confirmation_required: false,
      requires_valid_dialog: true, close_on_success: true }],
  }
  await page.route('**/api/v1/forms/field-example**', async route => {
    const request = route.request()
    const path = new URL(request.url()).pathname
    const body = request.postDataJSON() ?? {}
    if (request.method() === 'POST') calls.push({ path, body })
    let result = form
    if (path.endsWith('/options')) result = { items, total: items.length, has_more: false }
    else if (path.endsWith('/dialog/actions/apply')) result = {
      ...dialog, values: body.dialog_values, close_dialog: true, status: 'success',
      form_values: { [body.owner_field_path]: items.filter(item => body.dialog_values.choices.includes(item.id)).map(item => item.name).join('\n') },
    }
    else if (path.includes('/dialog')) result = { ...dialog, values: body.dialog_values ?? dialog.values }
    await route.fulfill({ json: result })
  })
  await page.goto(`${url.replace(/\/$/, '')}/forms/field-example`)
  await page.locator('[data-form-field-path="target_2"]').getByRole('button', { name: 'Выбрать из справочника' }).click()
  const modal = page.getByRole('dialog', { name: 'Выбор категорий' })
  await modal.getByRole('checkbox', { name: 'Категория Alpha' }).check()
  await modal.getByRole('checkbox', { name: 'Категория Beta' }).check()
  await expect.poll(() => calls.some(call => call.path.endsWith('/dialog/state') && call.body.dialog_values.choices.length === 2)).toBeTruthy()
  expect(calls.filter(call => call.path.includes('/dialog')).every(call => call.body.owner_field_path === 'target_2')).toBeTruthy()
  expect(calls.some(call => call.path.endsWith('/options'))).toBeTruthy()
  await modal.getByRole('button', { name: 'Заполнить поле' }).click()
  await expect(modal).toHaveCount(0)
  await expect(page.getByRole('textbox', { name: 'Описание · 2' })).toHaveValue('Категория Alpha\nКатегория Beta')
  await expect(page.getByRole('textbox', { name: 'Описание', exact: true })).toHaveValue('Первое описание')
  expect(calls.find(call => call.path.endsWith('/dialog/actions/apply')).body.owner_field_path).toBe('target_2')
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBeTruthy()
}
