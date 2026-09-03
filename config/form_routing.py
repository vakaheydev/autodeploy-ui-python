"""Доверенный каталог назначений форм для AI-маршрутизации заявок.

Это не справочник значений полей: в OpenCode передаются только назначение формы
и компактное описание её полей. Реальные reference ID по-прежнему разрешаются
локальным Python-кодом уже после выбора формы.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable

from forms.base_form import BaseForm


class FormRoutingConfigError(RuntimeError):
    """Каталог маршрутизации не соответствует зарегистрированным формам."""


@dataclass(frozen=True)
class FormRoutingDescription:
    purpose: str
    use_when: tuple[str, ...]
    avoid_when: tuple[str, ...]


FORM_ROUTING: dict[str, FormRoutingDescription] = {
    "api.create": FormRoutingDescription(
        purpose="Создать и зарегистрировать новое API в Gravitee.",
        use_when=(
            "В заявке явно требуется создание, регистрация или публикация нового API.",
            "Нужны имя API, владелец, context path и тип endpoint.",
        ),
        avoid_when=(
            "Нужно развернуть версию приложения, а не создать API.",
            "Нужно только включить или выключить существующие ingress.",
        ),
    ),
    "apps.deploy": FormRoutingDescription(
        purpose="Запустить деплой или повторный деплой версии приложения/сервиса.",
        use_when=(
            "В заявке явно требуется deploy/redeploy приложения или сервиса.",
            "Указаны приложение и версия, tag либо branch; могут быть namespace и replicas.",
        ),
        avoid_when=(
            "Требуется создать API в Gravitee без деплоя приложения.",
            "Требуется изменить только состояние ingress.",
        ),
    ),
    "other.ingress.enable": FormRoutingDescription(
        purpose="Включить существующие ingress для API.",
        use_when=(
            "В заявке явно требуется включить, активировать или открыть ingress.",
            "Указаны API, ingress, тип ingress и, при необходимости, тип канала.",
        ),
        avoid_when=(
            "Требуется выключить или закрыть ingress.",
            "Требуется создать новое API или выполнить деплой приложения.",
        ),
    ),
    "other.ingress.disable": FormRoutingDescription(
        purpose="Выключить существующие ingress для приложений.",
        use_when=(
            "В заявке явно требуется выключить, деактивировать или закрыть ingress.",
            "Указаны приложения и тип ingress; иногда указан тип канала.",
        ),
        avoid_when=(
            "Требуется включить или открыть ingress.",
            "Требуется создать новое API или выполнить деплой приложения.",
        ),
    ),
}


def build_form_catalog(forms: Iterable[BaseForm]) -> list[dict[str, Any]]:
    """Строит компактный каталог и требует явного описания каждой формы."""
    registered = sorted(forms, key=lambda item: item.form_id)
    registered_ids = {form.form_id for form in registered}
    configured_ids = set(FORM_ROUTING)
    missing = sorted(registered_ids - configured_ids)
    unknown = sorted(configured_ids - registered_ids)
    if missing or unknown:
        parts = []
        if missing:
            parts.append("нет описания: " + ", ".join(missing))
        if unknown:
            parts.append("форма не зарегистрирована: " + ", ".join(unknown))
        raise FormRoutingConfigError(
            "Некорректный config/form_routing.py (" + "; ".join(parts) + ")"
        )

    catalog: list[dict[str, Any]] = []
    for form in registered:
        routing = FORM_ROUTING[form.form_id]
        catalog.append({
            "form_id": form.form_id,
            "title": form.title,
            "category": form.category,
            "purpose": routing.purpose,
            "use_when": list(routing.use_when),
            "avoid_when": list(routing.avoid_when),
            "fields": [
                {
                    "key": field.key,
                    "label": field.label,
                    "type": field.field_type.value,
                    "required": field.required,
                }
                for field in form.fields
            ],
        })
    return catalog
