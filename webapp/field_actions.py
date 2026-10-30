"""Adapt field-owned callbacks to the existing form action/dialog lifecycle."""
from __future__ import annotations

import copy
from dataclasses import replace
from typing import Mapping

from forms.base_form import ServerAction, ServerActionDialog, ServerDialogAction
from forms.field_actions import FieldAction, FieldActionContext, FieldActionDialog, FieldDialogAction
from forms.fields import FieldType
from forms.result_config import ResultStatus


def target(runtime, form, path, values):
    from webapp.form_runtime import FormNotFoundError, _visible

    parts = path.split('.')
    if not parts or any(not part for part in parts):
        raise FormNotFoundError(path)
    current = values
    fields = form.fields
    for index, part in enumerate(parts):
        definition, _ = runtime._find_field_context(fields, part)
        if not _visible(definition, current):
            raise ValueError("Действие недоступно: поле скрыто")
        if part != definition.key and part not in current:
            raise ValueError("Экземпляр поля больше не существует")
        if index < len(parts) - 1:
            if definition.field_type is not FieldType.BLOCK:
                raise FormNotFoundError(path)
            current = current.get(part, {})
            if not isinstance(current, Mapping):
                raise ValueError("Некорректное значение блока")
            fields = definition.block_fields
    return definition, current.get(parts[-1])


def adapt(runtime, form, path, declaration):
    if not isinstance(declaration, FieldAction):
        raise TypeError("FieldDefinition.actions должен содержать FieldAction")
    if callable(declaration.handler) == (declaration.dialog is not None):
        raise ValueError("FieldAction должен объявлять ровно один handler или dialog")

    def context(environment, form_values, dialog_values=None, *, writable=False):
        definition, value = target(runtime, form, path, form_values)

        def set_value(new_value):
            if not writable:
                raise ValueError("set_value доступен только в обработчике кнопки")
            combined = copy.deepcopy(form_values)
            owner = combined
            parts = path.split('.')
            for part in parts[:-1]:
                owner = owner.setdefault(part, {})
            owner[parts[-1]] = new_value
            errors = []
            normalized = runtime._normalize_object(form.fields, combined, errors, environment, prefix="")
            structural = [item for item in errors if item["code"] in {"invalid_type", "plural_limit", "unknown_field"}]
            if structural:
                raise ValueError("Некорректное значение поля: " + '; '.join(item["message"] for item in structural))
            patch[parts[0]] = copy.deepcopy(normalized[parts[0]])

        patch = {}
        resolver = runtime.container.new_reference_resolver()
        return FieldActionContext(
            environment=environment, field_path=path, field=definition,
            value=copy.deepcopy(value), form_values=copy.deepcopy(form_values),
            dialog_values=copy.deepcopy(dialog_values or {}),
            http=form._runtime_http_client, services=form._runtime_services,
            _load_reference=resolver.resolve,
            _selected_items=lambda key: form.screen.get_field_items(key) if form.screen else [],
            _set_value=set_value,
        ), patch

    def run(environment, values):
        ctx, patch = context(environment, values, writable=True)
        result = runtime._server_action_result(declaration.handler(ctx))
        if result.status is not ResultStatus.ERROR:
            result = replace(result, values={**dict(result.values), **patch})
        return result

    dialog = declaration.dialog
    converted = None
    if dialog is not None:
        if not isinstance(dialog, FieldActionDialog):
            raise TypeError("FieldAction.dialog должен быть FieldActionDialog")
        if not isinstance(dialog.initial_values, Mapping) and not callable(dialog.initial_values):
            raise TypeError("FieldActionDialog.initial_values должен быть mapping или callable")
        if dialog.validate is not None and not callable(dialog.validate):
            raise TypeError("FieldActionDialog.validate должен быть callable")

        def initial(environment, values):
            ctx, _ = context(environment, values)
            return dialog.initial_values(ctx) if callable(dialog.initial_values) else dialog.initial_values

        def validate(environment, values, dialog_values):
            ctx, _ = context(environment, values, dialog_values)
            return dialog.validate(ctx)

        def button_adapter(button):
            if not isinstance(button, FieldDialogAction) or not callable(button.handler):
                raise TypeError("FieldActionDialog.actions должен содержать FieldDialogAction с handler")

            def run_button(environment, values, dialog_values):
                ctx, patch = context(environment, values, dialog_values, writable=True)
                result = runtime._dialog_action_result(button.handler(ctx))
                if result.status is not ResultStatus.ERROR:
                    result = replace(result, form_values={**dict(result.form_values), **patch})
                return result

            return ServerDialogAction(button.action_id, button.label, run_button,
                                      button.style, button.require_valid_dialog,
                                      button.confirmation_text, button.close_on_success)

        def check_fields(fields):
            for field in fields:
                if field.actions:
                    raise ValueError("Кнопки поля поддерживаются в основной форме; используйте actions диалога")
                check_fields(field.block_fields)
        check_fields(dialog.fields)
        converted = ServerActionDialog(dialog.title, dialog.fields,
            tuple(button_adapter(button) for button in dialog.actions),
            dialog.description, initial, validate if dialog.validate else None)
    return ServerAction(declaration.action_id, declaration.label, run if converted is None else None,
                        declaration.style, declaration.require_valid_form, declaration.confirmation_text, converted)
