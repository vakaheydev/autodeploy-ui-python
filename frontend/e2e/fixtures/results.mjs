import { installMarkdownFixture } from './markdown.mjs'

export const blockText = '  Операция завершена\n\tСохраните номер: TASK-42\nhttps://example.invalid/tasks/42?view=full&lang=ru\n'

export async function installResultFixture(page, { confirmed = true, reducedMotion = false } = {}) {
  await installMarkdownFixture(page)
  await page.emulateMedia({ reducedMotion: reducedMotion ? 'reduce' : 'no-preference' })
  await page.addInitScript(() => {
    window.resultScrolls = []
    const original = Element.prototype.scrollIntoView
    Element.prototype.scrollIntoView = function (options) {
      if (this.classList.contains('result-card')) window.resultScrolls.push(options)
      return original.call(this, options)
    }
  })
  let pollMode = 'waiting'
  let submissions = 0
  const initialContent = '{\n  "url": "https://example.invalid/' + 'long-path-'.repeat(25) + '"\n}'
  const initialBlocks = [{ text: blockText, label: 'Данные для передачи', copyable: true }]
  const document = {
    id: 'example.result', title: 'Проверка результата', category: 'other', category_label: 'Прочее',
    version: '1', confirm_submit: confirmed, itsm_support: false, http_method: 'POST',
    fields: Array.from({ length: 12 }, (_, i) => ({
      key: `field_${i}`, path: `field_${i}`, label: `Поле ${i + 1}`, type: 'text',
      required: false, visible: true, dynamic: false, default: '', placeholder: '', hint: '',
      file_type: '', width: 1, plural: false, plural_max: null,
    })), initial_values: {}, custom_actions: [],
  }
  await page.route('**/api/v1/forms/example.result**', async route => {
    const path = new URL(route.request().url()).pathname
    let result = document
    if (path.endsWith('/preview')) result = {
      valid: true, values: {}, errors: [], visible_fields: [], payload: {},
      confirmation_required: confirmed, confirmation_text: 'Отправить форму?', confirmation_token: 'fixture',
    }
    else if (path.endsWith('/submit')) result = {
      success: true, message: 'Принято: https://example.invalid/tasks/42.',
      submission_id: `submission-${++submissions}`, status: 'waiting', title: 'Заявка принята',
      content: initialContent, blocks: initialBlocks,
      response: {}, payload: {}, polling: true, poll_interval_ms: 500,
    }
    await route.fulfill({ json: result })
  })
  await page.route('**/api/v1/submissions/*/poll', async route => {
    if (pollMode === 'waiting') {
      await route.fulfill({ json: { polling: true, status: 'waiting', content: initialContent, blocks: initialBlocks } })
      return
    }
    const result = pollMode === 'stopped' ? { polling: false, status: 'stopped' } : {
      polling: true, status: 'success', content: 'Готово: https://example.invalid/final',
      blocks: [{ text: 'Новый блок\n  после опроса', label: 'Финальный результат', copyable: true }],
    }
    await route.fulfill({ json: result })
  })
  return { setPollMode: mode => { pollMode = mode } }
}
