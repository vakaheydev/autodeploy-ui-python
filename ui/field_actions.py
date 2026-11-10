"""Tkinter adapter for the same FieldAction declarations used by the web API."""
from __future__ import annotations

import copy
import math
import tkinter as tk
from tkinter import ttk
from types import SimpleNamespace
from collections.abc import Mapping

from forms.base_form import ServerActionResult, ServerDialogActionResult
from forms.field_actions import FieldActionContext, apply_field_return
from forms.fields import FieldDefinition, FieldType
from forms.result_config import ResultStatus
from ui import dialogs
from ui.widgets.field_factory import FieldFactory


def walk_widgets(widgets, prefix=""):
    for key, widget in widgets.items():
        path = f"{prefix}.{key}" if prefix else key
        yield path, widget
        yield from walk_widgets(widget.children, path)


class DesktopFieldActions:
    def __init__(self, screen, field, widget):
        self.screen, self.field, self.widget = screen, field, widget
        self.path = next(path for path, candidate in walk_widgets(screen._field_widgets)
                         if candidate is widget)
        self.environment = screen.app.current_environment.get()
        self.dialog_widget = None
        self.window = None

    def _selected(self, key):
        roots = []
        if self.dialog_widget:
            roots.append(self.dialog_widget.children)
        roots.append(self.screen._field_widgets)
        for widgets in roots:
            for path, widget in walk_widgets(widgets):
                if path == key:
                    item = widget.get_item()
                    return [item] if item is not None else widget.get_items()
        return []

    def context(self, *, writable=False):
        staged = []

        def set_value(value):
            if not writable:
                raise ValueError("set_value доступен только в обработчике кнопки")
            self._check_value(self.field, value)
            staged[:] = [copy.deepcopy(value)]

        app = self.screen.app
        context = FieldActionContext(
            environment=self.environment, field_path=self.path, field=self.field,
            value=copy.deepcopy(self.widget.get()),
            form_values=copy.deepcopy(self.screen._collect_form_data()),
            dialog_values=copy.deepcopy(self.dialog_widget.get() if self.dialog_widget else {}),
            http=app.http_client,
            services=SimpleNamespace(itsm=app.itsm_service, tfs=app.tfs_service, gravitee=app.gravitee_service),
            _load_reference=app.reference_resolver.resolve,
            _selected_items=self._selected, _set_value=set_value,
        )
        return context, staged

    @staticmethod
    def _check_value(field, value):
        kind = field.field_type
        if kind is FieldType.NUMBER and value is not None:
            try:
                if isinstance(value, bool) or not math.isfinite(float(value)):
                    raise ValueError()
            except (ValueError, TypeError, OverflowError):
                raise ValueError(f"Некорректное значение поля: {field.key}") from None
            return
        valid = value is None or (
            isinstance(value, bool) if kind is FieldType.CHECKBOX else
            isinstance(value, (int, float)) and not isinstance(value, bool) if kind is FieldType.NUMBER else
            isinstance(value, list) if kind is FieldType.MULTISELECT else
            isinstance(value, Mapping) if kind is FieldType.BLOCK else
            isinstance(value, str)
        )
        if not valid:
            raise ValueError(f"Некорректное значение поля: {field.key}")

    def _current(self):
        current = self.screen._collect_form_data()
        for part in self.path.split("."):
            if not isinstance(current, Mapping) or part not in current:
                return False
            current = current[part]
        return (self.widget.widget.winfo_exists()
                and self.screen.app.current_environment.get() == self.environment
                and any(candidate is self.widget for _, candidate in walk_widgets(self.screen._field_widgets)))

    def run(self, action):
        if callable(action.handler) == (action.dialog is not None):
            raise ValueError("FieldAction должен объявлять ровно один handler или dialog")
        if action.require_valid_form:
            errors = self.screen._form.validate(self.screen._collect_form_data())
            if errors:
                raise ValueError("\n".join(map(str, errors)))
        if action.confirmation_text and not dialogs.show_confirm(self.screen, action.label, action.confirmation_text):
            return
        if action.dialog is not None:
            self.open_dialog(action.dialog)
        else:
            self.execute(action.handler)

    def execute(self, handler, button=None):
        if not self._current():
            raise ValueError("Поле или окружение изменилось; откройте действие заново")
        context, staged = self.context(writable=True)
        result = apply_field_return(context, handler(context))
        if isinstance(result, (ServerActionResult, ServerDialogActionResult)):
            result = vars(result)
        result = dict(result or {})
        status = ResultStatus(result.get("status", ResultStatus.SUCCESS))
        if status is ResultStatus.ERROR:
            dialogs.show_error(self.window or self.screen, result.get("title") or "Ошибка", result.get("message", "Ошибка действия"))
            return
        if not self._current():
            raise ValueError("Поле или окружение изменилось; результат не применён")
        patch = result.get("form_values", result.get("values", {}))
        if patch:
            self.screen.apply_form_data(patch)
        if staged:
            self.widget.set_and_notify(staged[-1])
        if self.dialog_widget and result.get("dialog_values"):
            self.dialog_widget.set(result["dialog_values"])
        if result.get("message"):
            dialogs.show_info(self.window or self.screen, result.get("title") or "Результат", result["message"])
        close = result.get("close_dialog")
        if button and (button.close_on_success if close is None else close):
            self.window.destroy()

    def open_dialog(self, declaration):
        def check_fields(fields):
            for field in fields:
                if field.actions:
                    raise ValueError("Кнопки поля поддерживаются в основной форме; используйте actions диалога")
                check_fields(field.block_fields)
        check_fields(declaration.fields)
        ids = [button.action_id for button in declaration.actions]
        if len(set(ids)) != len(ids):
            raise ValueError("FieldDialogAction.action_id должны быть уникальными")
        context, _ = self.context()
        initial = declaration.initial_values(context) if callable(declaration.initial_values) else declaration.initial_values
        window = self.window = tk.Toplevel(self.screen)
        window.title(declaration.title)
        window.transient(self.screen.winfo_toplevel())
        if declaration.description:
            ttk.Label(window, text=declaration.description, wraplength=560).pack(fill=tk.X, padx=12, pady=8)
        factory = FieldFactory()

        def load(field, extra_params=None):
            if field.reference is None:
                return []
            params = dict(extra_params or {})
            current = self.dialog_widget.get() if self.dialog_widget else dict(initial)
            form = self.screen._collect_form_data()
            for dependency in field.reference_dependencies:
                if (dependency.parameter or dependency.field) in params:
                    continue
                source = form if dependency.scope == "form" else current
                value = source.get(dependency.field)
                if dependency.item_field:
                    items = self._selected(dependency.field)
                    value = items[0].get(dependency.item_field) if items else None
                if value in (None, "", []):
                    return []
                params[dependency.parameter or dependency.field] = value
            return self.screen.app.reference_resolver.resolve(field.reference, self.environment, params)

        def refresh(field, _button):
            self.screen.app.reference_cache.invalidate(field.reference.resource, self.environment)
            self.dialog_widget.refresh_sub_ref(field.key, load(field))

        block = FieldDefinition("dialog", declaration.title, FieldType.BLOCK, block_fields=list(declaration.fields))
        self.dialog_widget = factory.create(window, block, ref_loader=load, on_refresh=refresh)
        self.dialog_widget.widget.pack(fill=tk.BOTH, expand=True, padx=12, pady=12)
        self.dialog_widget.set(dict(initial))

        def reload_dependents():
            for field in declaration.fields:
                if field.reference_dependencies:
                    value = self.dialog_widget.children[field.key].get()
                    self.dialog_widget.refresh_sub_ref(field.key, load(field))
                    self.dialog_widget.children[field.key].set(value)
        reload_dependents()

        def invoke(button):
            try:
                context, _ = self.context()
                if button.require_valid_dialog:
                    errors = []
                    for field in declaration.fields:
                        if field.condition and not field.condition(context.dialog_values):
                            continue
                        if field.required and context.dialog_values.get(field.key) in (None, "", []):
                            errors.append(f'Поле "{field.label}" обязательно для заполнения')
                    if declaration.validate:
                        errors.extend(declaration.validate(context) or [])
                    if errors:
                        raise ValueError("\n".join(str(error) for error in errors))
                if button.confirmation_text and not dialogs.show_confirm(window, button.label, button.confirmation_text):
                    return
                self.execute(button.handler, button)
            except Exception as exc:
                dialogs.show_error(window, "Ошибка", str(exc))

        footer = ttk.Frame(window)
        footer.pack(fill=tk.X, padx=12, pady=12)
        for button in declaration.actions:
            ttk.Button(footer, text=button.label, style=f"{button.style}.TButton",
                       command=lambda b=button: invoke(b)).pack(side=tk.LEFT, padx=4)
        ttk.Button(footer, text="Отмена", command=window.destroy).pack(side=tk.RIGHT)
