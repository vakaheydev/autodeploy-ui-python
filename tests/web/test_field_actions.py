from dataclasses import replace
from unittest.mock import Mock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from forms.base_form import BaseForm, ServerActionResult, ServerDialogActionResult
from forms.field_actions import FieldAction, FieldActionDialog, FieldDialogAction
from forms.fields import FieldDefinition, FieldType, ReferenceConfig
from forms.loader import register_all_forms
from forms.registry import FormRegistry
from forms.result_config import ResultStatus
from webapp.api import router
from webapp.container import ApplicationContainer
from webapp.form_runtime import form_version, FormNotFoundError
from webapp.settings import WebSettings


class ActionForm(BaseForm):
    form_id = 'example.field-actions'
    title = 'Field actions'
    category = 'other'

    def __init__(self):
        self.calls = []

    def direct(self, ctx):
        self.calls.append((ctx.field_path, ctx.environment, ctx.value))
        items = ctx.load_reference(ReferenceConfig('local', 'api_categories.json'))
        assert items and ctx.services.gravitee is not None
        result = ctx.http.get('https://example.invalid/value')
        ctx.set_value(result['value'])

    def choose(self, ctx):
        self.calls.append((ctx.field_path, ctx.dialog_values['choices']))
        items = ctx.get_selected_items('choices')
        ctx.set_value(', '.join(item['name'] for item in items))
        return ServerDialogActionResult(message='Выбор применён')

    @property
    def fields(self):
        actions = (
            FieldAction('load', 'Загрузить', handler=self.direct),
            FieldAction('confirmed', 'Подтвердить', handler=self.direct, confirmation_text='Обновить поле?'),
            FieldAction('choose', 'Выбрать', dialog=FieldActionDialog(
                title='Выберите категории',
                fields=[FieldDefinition('choices', 'Категории', FieldType.MULTISELECT,
                    reference=ReferenceConfig('local', 'api_categories.json'))],
                actions=[FieldDialogAction('apply', 'Применить', self.choose, confirmation_text='Применить выбор?')],
            )),
        )
        return [
            FieldDefinition('target', 'Текст', FieldType.TEXT, required=False, plural=True, actions=actions),
            FieldDefinition('block', 'Блок', FieldType.BLOCK, required=False, plural=True, block_fields=[
                FieldDefinition('value', 'Значение', FieldType.TEXT, required=False, actions=actions),
                FieldDefinition('sibling', 'Соседнее поле', FieldType.TEXT, required=False),
            ]),
            FieldDefinition('enabled', 'Показать', FieldType.CHECKBOX, default=False),
            FieldDefinition('hidden', 'Скрытое', FieldType.TEXT, required=False,
                            condition=lambda values: values.get('enabled'), actions=actions),
        ]

    def build_payload(self, form_data):
        return form_data

    def get_submit_endpoint(self, environment):
        return 'https://example.invalid/submit'


@pytest.fixture
def runtime(tmp_path, monkeypatch):
    from pathlib import Path
    root = Path(__file__).resolve().parents[2]
    settings = WebSettings(host='127.0.0.1', port=8765, project_root=root,
        data_dir=tmp_path / 'data', env_file=tmp_path / '.env', static_dir=root / 'webapp/static',
        log_dir=tmp_path / 'logs', max_request_bytes=2 * 1024 * 1024,
        auto_connect_opencode=False, open_browser=False)
    container = ApplicationContainer(settings)
    client = Mock()
    client.get.return_value = {'value': 'Загружено'}
    monkeypatch.setattr(container, 'new_http_client', lambda: client)
    form = ActionForm()
    FormRegistry().register(form)
    yield container.forms, form, client
    container.opencode_manager.stop()
    FormRegistry().clear()
    register_all_forms()


def test_declaration_is_read_only_and_direct_handler_updates_exact_nested_instance(runtime):
    api, form, http = runtime
    values = {'target': 'old', 'block': {'value': 'first'}, 'block_2': {'value': 'second', 'sibling': 'keep'}}
    document = api.describe(form.form_id, 'test_int', values)
    assert [a['id'] for a in document['fields'][0]['actions']] == ['load', 'confirmed', 'choose']
    assert not form.calls
    http.get.assert_not_called()
    result = api.run_action(form.form_id, 'load', 'test_int', values, document['version'], '', owner_field_path='block_2.value')
    assert result['values'] == {'block_2': {'value': 'Загружено', 'sibling': 'keep'}}
    assert values['block_2']['value'] == 'second'
    assert form.calls == [('block_2.value', 'test_int', 'second')]
    http.get.assert_called_once_with('https://example.invalid/value')


def test_field_confirmation_is_bound_to_owning_instance_and_values(runtime):
    api, form, _ = runtime
    values = {'target': 'one', 'target_2': 'two'}
    version = form_version(form)
    first = api.run_action(form.form_id, 'confirmed', 'test_int', values, version, '', owner_field_path='target')
    assert first['confirmation_required']
    wrong = api.run_action(form.form_id, 'confirmed', 'test_int', values, version, first['confirmation_token'], owner_field_path='target_2')
    assert wrong['confirmation_required']
    assert not form.calls
    done = api.run_action(form.form_id, 'confirmed', 'test_int', values, version, wrong['confirmation_token'], owner_field_path='target_2')
    assert done['values'] == {'target_2': 'Загружено'}


@pytest.mark.parametrize('path', ['hidden', 'target_3', 'block_3.value', 'unknown', 'block.missing', '.target'])
def test_hidden_missing_and_deleted_fields_cannot_run_handlers(runtime, path):
    api, form, _ = runtime
    with pytest.raises((ValueError, FormNotFoundError)):
        api.run_action(form.form_id, 'load', 'test_int', {'target': ''}, form_version(form), '', owner_field_path=path)
    assert not form.calls


def test_dialog_reference_selection_through_http_updates_only_owning_field(runtime):
    api, form, _ = runtime
    app = FastAPI()
    app.state.container = api.container
    app.include_router(router)
    base = f'/api/v1/forms/{form.form_id}/actions/choose/dialog'
    body = {'environment': 'test_int', 'form_values': {'target': 'one', 'target_2': 'two'},
            'form_version': form_version(form), 'owner_field_path': 'target_2'}
    with TestClient(app) as client:
        opened = client.post(base, json=body)
        assert opened.status_code == 200, opened.text
        assert opened.json()['owner_field_path'] == 'target_2'
        options = client.post(base + '/fields/choices/options', json={**body, 'dialog_values': {}, 'query': ''})
        assert options.status_code == 200, options.text
        item = options.json()['items'][0]
        picked = {**body, 'dialog_values': {'choices': [item['id']]}}
        initial = client.post(base + '/actions/apply', json=picked).json()
        assert initial['confirmation_required'] and not form.calls
        confirmed = client.post(base + '/actions/apply', json={**picked, 'confirmation_token': initial['confirmation_token']})
        assert confirmed.status_code == 200, confirmed.text
        assert confirmed.json()['form_values'] == {'target_2': item['name']}
        assert confirmed.json()['close_dialog'] is True
        direct = client.post(f'/api/v1/forms/{form.form_id}/actions/load', json={
            'environment': 'test_int', 'values': body['form_values'], 'form_version': body['form_version'],
            'owner_field_path': 'target_2',
        })
        assert direct.status_code == 200, direct.text
        assert direct.json()['values'] == {'target_2': 'Загружено'}


def test_declared_field_actions_change_schema_version(runtime, monkeypatch):
    _, form, _ = runtime
    before = form_version(form)
    fields = form.fields
    fields[0] = replace(fields[0], actions=(replace(fields[0].actions[0], label='Новая подпись'),))
    monkeypatch.setattr(ActionForm, 'fields', property(lambda self: fields))
    assert form_version(form) != before


def test_error_result_does_not_apply_staged_value(runtime, monkeypatch):
    api, form, _ = runtime
    def failed(ctx):
        ctx.set_value('Не применять')
        return ServerActionResult(status=ResultStatus.ERROR, message='Не удалось')
    fields = [FieldDefinition('target', 'Текст', FieldType.TEXT, actions=(FieldAction('fail', 'Ошибка', handler=failed),))]
    monkeypatch.setattr(ActionForm, 'fields', property(lambda self: fields))
    result = api.run_action(form.form_id, 'fail', 'test_int', {'target': 'keep'}, form_version(form), '', owner_field_path='target')
    assert result['status'] == 'error'
    assert result['values'] == {}


def test_dialog_initialization_can_load_data_once_and_cannot_set_the_owner(runtime, monkeypatch):
    api, form, http = runtime
    calls = []
    def initial(ctx):
        calls.append(ctx.field_path)
        with pytest.raises(ValueError, match='только в обработчике'):
            ctx.set_value('wrong')
        return {'comment': ctx.http.get('https://example.invalid/initial')['value']}
    dialog = FieldActionDialog('Окно', [FieldDefinition('comment', 'Комментарий', FieldType.TEXT)],
                               [FieldDialogAction('ok', 'OK', lambda ctx: None)], initial_values=initial)
    fields = [FieldDefinition('target', 'Текст', FieldType.TEXT, actions=(FieldAction('open', 'Открыть', dialog=dialog),))]
    monkeypatch.setattr(ActionForm, 'fields', property(lambda self: fields))
    opened = api.open_action_dialog(form.form_id, 'open', 'test_int', {'target': 'keep'}, form_version(form), owner_field_path='target')
    assert opened['values'] == {'comment': 'Загружено'}
    api.action_dialog_state(form.form_id, 'open', 'test_int', {'target': 'keep'}, {'comment': 'edited'}, form_version(form), owner_field_path='target')
    assert calls == ['target']
    http.get.assert_called_once()


def test_invalid_value_and_duplicate_buttons_are_rejected(runtime, monkeypatch):
    api, form, _ = runtime
    action = FieldAction('bad', 'Заполнить', handler=lambda ctx: ctx.set_value('not a number'))
    fields = [FieldDefinition('number', 'Число', FieldType.NUMBER, actions=(action,))]
    monkeypatch.setattr(ActionForm, 'fields', property(lambda self: fields))
    with pytest.raises(ValueError, match='Некорректное значение'):
        api.run_action(form.form_id, 'bad', 'test_int', {'number': 42}, form_version(form), '', owner_field_path='number')
    fields[0] = replace(fields[0], actions=(action, action))
    with pytest.raises(ValueError, match='уникальные'):
        api.describe(form.form_id, 'test_int')
