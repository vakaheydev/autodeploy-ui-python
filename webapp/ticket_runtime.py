"""Validated server-side projection of a private corporate ticket provider."""
from __future__ import annotations

import dataclasses
import hashlib
import json
import math
import re
from typing import Any, Mapping, Sequence
from urllib.parse import urlsplit

from tickets import (
    TicketAction,
    TicketActionResult,
    TicketAttribute,
    TicketCard,
    TicketContext,
    TicketFilterDefinition,
    TicketFilterOption,
    TicketListConfiguration,
    TicketListItem,
    TicketListRequest,
    TicketNotFound,
    TicketPage,
    TicketSection,
    TicketSortDefinition,
    TicketUserError,
)


_IDENTIFIER = re.compile(r"^[A-Za-z][A-Za-z0-9_.:-]{0,99}$")
_COLOR = re.compile(r"^#[0-9a-fA-F]{3}(?:[0-9a-fA-F]{3})?$")
_FILTER_KINDS = frozenset({"text", "select", "multiselect", "date", "boolean"})
_ATTRIBUTE_KINDS = frozenset(
    {"text", "multiline", "code", "datetime", "badge", "json"}
)
_TONES = frozenset({"default", "info", "success", "warning", "danger"})
_ACTION_STYLES = frozenset(
    {"primary", "secondary", "success", "danger", "warning"}
)


class TicketsNotConfiguredError(RuntimeError):
    """The optional private ticket provider is not connected."""


class TicketContractError(ValueError):
    """A private provider returned a document outside the public contract."""


class TicketCardVersionConflict(RuntimeError):
    """The browser is trying to execute a stale card action."""


def _text(value: Any, *, name: str, limit: int, required: bool = False) -> str:
    result = str(value or "").replace("\x00", "").strip()
    if required and not result:
        raise TicketContractError(f"{name} не должен быть пустым")
    if len(result) > limit:
        raise TicketContractError(f"{name} превышает {limit} символов")
    return result


def _identifier(value: Any, *, name: str) -> str:
    result = _text(value, name=name, limit=100, required=True)
    if not _IDENTIFIER.fullmatch(result):
        raise TicketContractError(
            f"{name} должен начинаться с латинской буквы и содержать только "
            "буквы, цифры, точку, двоеточие, дефис или подчёркивание"
        )
    return result


def _json_safe(value: Any, *, depth: int = 0) -> Any:
    if depth > 12:
        raise TicketContractError("Данные заявки имеют слишком большую вложенность")
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise TicketContractError("Данные заявки содержат неконечное число")
        return value
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return _json_safe(dataclasses.asdict(value), depth=depth + 1)
    if isinstance(value, Mapping):
        if len(value) > 500:
            raise TicketContractError("Объект заявки содержит больше 500 полей")
        return {
            str(key)[:300]: _json_safe(item, depth=depth + 1)
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple)):
        if len(value) > 2_000:
            raise TicketContractError("Массив данных заявки содержит больше 2000 элементов")
        return [_json_safe(item, depth=depth + 1) for item in value]
    return _text(value, name="Значение заявки", limit=100_000)


def _bounded_document(value: Any, *, limit: int = 2 * 1024 * 1024) -> Any:
    result = _json_safe(value)
    encoded = json.dumps(
        result, ensure_ascii=False, separators=(",", ":"), default=str
    ).encode("utf-8")
    if len(encoded) > limit:
        raise TicketContractError("Ответ сервиса заявок превышает допустимый размер")
    return result


class TicketRuntime:
    """Call the private provider and expose only bounded JSON documents."""

    def __init__(self, container: Any) -> None:
        self.container = container

    @property
    def enabled(self) -> bool:
        return self.container.ticket_provider is not None

    def context(self, environment: str) -> TicketContext:
        try:
            self.container.forms._ensure_environment(environment)
        except ValueError as exc:
            raise TicketUserError(str(exc)) from exc
        client = self.container.new_http_client()
        return TicketContext(
            environment=environment,
            env_manager=self.container.env_manager,
            http_client=client,
            services=self.container.service_provider(
                self.container.env_manager, client
            ),
        )

    def configuration(self, environment: str) -> dict[str, Any]:
        if not self.enabled:
            return {
                "enabled": False,
                "description": "",
                "filters": [],
                "sorts": [],
                "default_sort": "",
                "default_direction": "desc",
                "page_size": 25,
                "empty_title": "Раздел заявок не подключён",
                "empty_text": (
                    "Укажите корпоративную фабрику TicketProvider в настройках "
                    "расширений."
                ),
            }
        context = self.context(environment)
        raw = self.container.ticket_provider.get_list_configuration(context)
        return self._configuration_document(self._configuration(raw), enabled=True)

    def query(
        self,
        *,
        environment: str,
        query: str,
        filters: Mapping[str, Any],
        sort_key: str,
        sort_direction: str,
        offset: int,
        limit: int,
    ) -> dict[str, Any]:
        provider = self._provider()
        context = self.context(environment)
        configuration = self._configuration(
            provider.get_list_configuration(context)
        )
        request = self._list_request(
            configuration,
            environment=environment,
            query=query,
            filters=filters,
            sort_key=sort_key,
            sort_direction=sort_direction,
            offset=offset,
            limit=limit,
        )
        raw = (
            provider.find_tickets(context, request)
            if request.query
            else provider.load_current_tickets(context, request)
        )
        if not isinstance(raw, TicketPage):
            raise TicketContractError(
                "load_current_tickets/find_tickets должен вернуть TicketPage"
            )
        if not isinstance(raw.total, int) or isinstance(raw.total, bool) or raw.total < 0:
            raise TicketContractError("TicketPage.total должен быть целым числом >= 0")
        items = tuple(raw.items)
        if len(items) > request.limit:
            raise TicketContractError(
                "TicketPage.items содержит больше элементов, чем request.limit"
            )
        if raw.total < request.offset + len(items):
            raise TicketContractError(
                "TicketPage.total меньше фактической позиции последнего элемента"
            )
        documents = [self._list_item(item) for item in items]
        identifiers = [item["id"] for item in documents]
        if len(identifiers) != len(set(identifiers)):
            raise TicketContractError("TicketPage содержит повторяющиеся ticket_id")
        return _bounded_document({
            "items": documents,
            "total": raw.total,
            "offset": request.offset,
            "limit": request.limit,
            "has_more": request.offset + len(documents) < raw.total,
        })

    def card(self, ticket_id: str, environment: str) -> dict[str, Any]:
        provider = self._provider()
        context = self.context(environment)
        card = self._load_card(provider, context, ticket_id)
        return _bounded_document(self._card_document(card, environment))

    def run_action(
        self,
        *,
        action_id: str,
        ticket_id: str,
        environment: str,
        card_version: str,
        confirmation_token: str = "",
    ) -> dict[str, Any]:
        provider = self._provider()
        context = self.context(environment)
        card = self._load_card(provider, context, ticket_id)
        current_version = self._card_version(card)
        if not card_version or card_version != current_version:
            raise TicketCardVersionConflict(
                "Карточка заявки изменилась. Обновите её перед выполнением действия."
            )
        try:
            normalized_action_id = _identifier(
                action_id, name="TicketAction.action_id"
            )
        except TicketContractError as exc:
            raise TicketUserError("Некорректный идентификатор действия") from exc
        for item in card.actions:
            self._action_document(item)
        action = next(
            (
                item
                for item in card.actions
                if _identifier(item.action_id, name="TicketAction.action_id")
                == normalized_action_id
            ),
            None,
        )
        if action is None:
            raise TicketNotFound("Действие заявки не найдено")
        self._action_document(action)
        if action.disabled_reason:
            raise TicketUserError(_text(
                action.disabled_reason,
                name="TicketAction.disabled_reason",
                limit=2_000,
                required=True,
            ))
        fingerprint = self.container.fingerprint(
            f"ticket:{normalized_action_id}",
            environment,
            {"ticket_id": card.ticket_id},
            current_version,
        )
        if action.confirmation_text and not self.container.confirmations.consume(
            confirmation_token, fingerprint
        ):
            return {
                "success": False,
                "confirmation_required": True,
                "confirmation_text": _text(
                    action.confirmation_text,
                    name="TicketAction.confirmation_text",
                    limit=4_000,
                    required=True,
                ),
                "confirmation_token": self.container.confirmations.issue(fingerprint),
            }

        result = self._action_result(action.handler(context, card.ticket_id))
        updated = (
            self._load_card(provider, context, card.ticket_id)
            if result.reload_card
            else card
        )
        return _bounded_document({
            "success": True,
            "message": _text(
                result.message,
                name="TicketActionResult.message",
                limit=4_000,
            ) or "Действие выполнено",
            "card": self._card_document(updated, environment),
            "data": result.data,
        })

    def _provider(self) -> Any:
        if not self.enabled:
            raise TicketsNotConfiguredError(
                "Корпоративный сервис заявок не подключён"
            )
        return self.container.ticket_provider

    def _configuration(self, value: Any) -> TicketListConfiguration:
        if not isinstance(value, TicketListConfiguration):
            raise TicketContractError(
                "get_list_configuration должен вернуть TicketListConfiguration"
            )
        if value.default_direction not in {"asc", "desc"}:
            raise TicketContractError(
                "TicketListConfiguration.default_direction должен быть asc или desc"
            )
        if not isinstance(value.page_size, int) or isinstance(value.page_size, bool):
            raise TicketContractError("TicketListConfiguration.page_size должен быть int")
        if not 1 <= value.page_size <= 200:
            raise TicketContractError(
                "TicketListConfiguration.page_size должен быть от 1 до 200"
            )
        if any(not isinstance(item, TicketFilterDefinition) for item in value.filters):
            raise TicketContractError(
                "filters должны содержать TicketFilterDefinition"
            )
        if any(not isinstance(item, TicketSortDefinition) for item in value.sorts):
            raise TicketContractError("sorts должны содержать TicketSortDefinition")
        filter_keys = [
            _identifier(item.key, name="TicketFilterDefinition.key")
            for item in value.filters
        ]
        sort_keys = [
            _identifier(item.key, name="TicketSortDefinition.key")
            for item in value.sorts
        ]
        if value.default_sort and value.default_sort not in sort_keys:
            raise TicketContractError(
                "TicketListConfiguration.default_sort не объявлен в sorts"
            )
        if len(filter_keys) != len(set(filter_keys)):
            raise TicketContractError("Ключи фильтров заявок должны быть уникальными")
        if len(sort_keys) != len(set(sort_keys)):
            raise TicketContractError("Ключи сортировок заявок должны быть уникальными")
        if len(value.filters) > 30 or len(value.sorts) > 30:
            raise TicketContractError("Допустимо не более 30 фильтров и сортировок")
        for item in value.filters:
            self._filter_document(item)
        for item in value.sorts:
            self._sort_document(item)
        return value

    def _configuration_document(
        self, value: TicketListConfiguration, *, enabled: bool
    ) -> dict[str, Any]:
        filters = [self._filter_document(item) for item in value.filters]
        sorts = [self._sort_document(item) for item in value.sorts]
        return _bounded_document({
            "enabled": enabled,
            "description": _text(
                value.description, name="TicketListConfiguration.description", limit=4_000
            ),
            "filters": filters,
            "sorts": sorts,
            "default_sort": value.default_sort,
            "default_direction": value.default_direction,
            "page_size": value.page_size,
            "empty_title": _text(
                value.empty_title,
                name="TicketListConfiguration.empty_title",
                limit=500,
                required=True,
            ),
            "empty_text": _text(
                value.empty_text,
                name="TicketListConfiguration.empty_text",
                limit=2_000,
            ),
        })

    def _filter_document(self, value: Any) -> dict[str, Any]:
        if not isinstance(value, TicketFilterDefinition):
            raise TicketContractError(
                "filters должны содержать TicketFilterDefinition"
            )
        key = _identifier(value.key, name="TicketFilterDefinition.key")
        kind = str(value.kind).strip().casefold()
        if kind not in _FILTER_KINDS:
            raise TicketContractError(f"Неизвестный тип фильтра {kind!r}")
        options = [self._filter_option(item) for item in value.options]
        if kind not in {"select", "multiselect"} and options:
            raise TicketContractError(
                f"Фильтр {key!r} типа {kind} не должен содержать options"
            )
        if kind in {"select", "multiselect"} and len(options) > 500:
            raise TicketContractError(f"Фильтр {key!r} содержит больше 500 options")
        option_values = [item["value"] for item in options]
        if len(option_values) != len(set(option_values)):
            raise TicketContractError(f"Фильтр {key!r} содержит повторяющиеся options")
        default = self._filter_value(value, value.default, allow_empty=True)
        return {
            "key": key,
            "label": _text(
                value.label,
                name="TicketFilterDefinition.label",
                limit=300,
                required=True,
            ),
            "kind": kind,
            "options": options,
            "placeholder": _text(
                value.placeholder,
                name="TicketFilterDefinition.placeholder",
                limit=500,
            ),
            "default": default,
        }

    @staticmethod
    def _filter_option(value: Any) -> dict[str, str]:
        if not isinstance(value, TicketFilterOption):
            raise TicketContractError(
                "options должны содержать TicketFilterOption"
            )
        return {
            "value": _text(
                value.value,
                name="TicketFilterOption.value",
                limit=500,
                required=True,
            ),
            "label": _text(
                value.label,
                name="TicketFilterOption.label",
                limit=500,
                required=True,
            ),
        }

    @staticmethod
    def _sort_document(value: Any) -> dict[str, str]:
        if not isinstance(value, TicketSortDefinition):
            raise TicketContractError("sorts должны содержать TicketSortDefinition")
        return {
            "key": _identifier(value.key, name="TicketSortDefinition.key"),
            "label": _text(
                value.label,
                name="TicketSortDefinition.label",
                limit=300,
                required=True,
            ),
        }

    def _list_request(
        self,
        configuration: TicketListConfiguration,
        *,
        environment: str,
        query: str,
        filters: Mapping[str, Any],
        sort_key: str,
        sort_direction: str,
        offset: int,
        limit: int,
    ) -> TicketListRequest:
        definitions = {
            _identifier(item.key, name="TicketFilterDefinition.key"): item
            for item in configuration.filters
        }
        unknown = sorted(set(filters) - set(definitions))
        if unknown:
            raise TicketUserError("Неизвестные фильтры: " + ", ".join(unknown))
        normalized_filters = {}
        for key, raw in filters.items():
            value = self._filter_value(definitions[key], raw, allow_empty=True)
            if value not in (None, "", [], False):
                normalized_filters[key] = value
        sort_keys = {
            _identifier(item.key, name="TicketSortDefinition.key")
            for item in configuration.sorts
        }
        selected_sort = str(sort_key or configuration.default_sort).strip()
        if selected_sort and selected_sort not in sort_keys:
            raise TicketUserError("Неизвестная сортировка заявок")
        direction = str(sort_direction or configuration.default_direction).casefold()
        if direction not in {"asc", "desc"}:
            raise TicketUserError("Направление сортировки должно быть asc или desc")
        return TicketListRequest(
            environment=environment,
            query=_text(query, name="Поисковый запрос", limit=500),
            filters=normalized_filters,
            sort_key=selected_sort,
            sort_direction=direction,
            offset=offset,
            limit=min(limit, 200),
        )

    def _filter_value(
        self, definition: TicketFilterDefinition, value: Any, *, allow_empty: bool
    ) -> Any:
        kind = str(definition.kind).strip().casefold()
        allowed = {str(item.value) for item in definition.options}
        if value is None:
            return None
        if kind == "boolean":
            if not isinstance(value, bool):
                raise TicketUserError(f"Фильтр {definition.label!r} должен быть boolean")
            return value
        if isinstance(value, (Mapping, list, tuple)) and kind != "multiselect":
            raise TicketUserError(
                f"Фильтр {definition.label!r} должен быть строкой"
            )
        if kind == "multiselect":
            if value in ("", ()):
                return []
            if not isinstance(value, (list, tuple)):
                raise TicketUserError(f"Фильтр {definition.label!r} должен быть массивом")
            if len(value) > 100:
                raise TicketUserError(f"Фильтр {definition.label!r} содержит слишком много значений")
            result = list(dict.fromkeys(
                _text(item, name=f"Фильтр {definition.label}", limit=500)
                for item in value
                if str(item).strip()
            ))
            if allowed and any(item not in allowed for item in result):
                raise TicketUserError(f"Фильтр {definition.label!r} содержит неизвестное значение")
            return result
        result = _text(value, name=f"Фильтр {definition.label}", limit=1_000)
        if not result and allow_empty:
            return ""
        if kind == "select" and allowed and result not in allowed:
            raise TicketUserError(f"Фильтр {definition.label!r} содержит неизвестное значение")
        return result

    def _list_item(self, value: Any) -> dict[str, Any]:
        if not isinstance(value, TicketListItem):
            raise TicketContractError("TicketPage.items должны содержать TicketListItem")
        attributes = tuple(value.attributes)
        if len(attributes) > 20:
            raise TicketContractError("TicketListItem содержит больше 20 attributes")
        documents = [self._attribute(item) for item in attributes]
        keys = [item["key"] for item in documents]
        if len(keys) != len(set(keys)):
            raise TicketContractError(
                "TicketListItem.attributes должны иметь уникальные key"
            )
        return {
            "id": _text(
                value.ticket_id, name="TicketListItem.ticket_id", limit=500, required=True
            ),
            "title": _text(
                value.title, name="TicketListItem.title", limit=1_000, required=True
            ),
            "subtitle": _text(
                value.subtitle, name="TicketListItem.subtitle", limit=2_000
            ),
            "status": _text(
                value.status, name="TicketListItem.status", limit=300
            ),
            "status_tone": self._tone(value.status_tone),
            "updated_at": _text(
                value.updated_at, name="TicketListItem.updated_at", limit=300
            ),
            "attributes": documents,
        }

    def _load_card(
        self, provider: Any, context: TicketContext, ticket_id: str
    ) -> TicketCard:
        identifier = _text(ticket_id, name="ticket_id", limit=500, required=True)
        try:
            value = provider.load_ticket_card_by_id(context, identifier)
        except TicketNotFound:
            raise
        if value is None:
            raise TicketNotFound(identifier)
        if not isinstance(value, TicketCard):
            raise TicketContractError(
                "load_ticket_card_by_id должен вернуть TicketCard"
            )
        if str(value.ticket_id).strip() != identifier:
            raise TicketContractError(
                "TicketCard.ticket_id не совпадает с запрошенным идентификатором"
            )
        return value

    def _card_document(self, value: TicketCard, environment: str) -> dict[str, Any]:
        sections = tuple(value.sections)
        actions = tuple(value.actions)
        if len(sections) > 30 or len(actions) > 30:
            raise TicketContractError("Карточка содержит больше 30 секций или действий")
        section_documents = [self._section(item) for item in sections]
        action_documents = [self._action_document(item) for item in actions]
        section_ids = [item["id"] for item in section_documents]
        action_ids = [item["id"] for item in action_documents]
        if len(section_ids) != len(set(section_ids)):
            raise TicketContractError("TicketSection.section_id должны быть уникальными")
        if len(action_ids) != len(set(action_ids)):
            raise TicketContractError("TicketAction.action_id должны быть уникальными")
        return {
            "id": _text(
                value.ticket_id, name="TicketCard.ticket_id", limit=500, required=True
            ),
            "title": _text(
                value.title, name="TicketCard.title", limit=1_000, required=True
            ),
            "subtitle": _text(
                value.subtitle, name="TicketCard.subtitle", limit=2_000
            ),
            "description": _text(
                value.description, name="TicketCard.description", limit=20_000
            ),
            "status": _text(value.status, name="TicketCard.status", limit=300),
            "status_tone": self._tone(value.status_tone),
            "updated_at": _text(
                value.updated_at, name="TicketCard.updated_at", limit=300
            ),
            "environment": environment,
            "version": self._card_version(value),
            "sections": section_documents,
            "actions": action_documents,
        }

    def _section(self, value: Any) -> dict[str, Any]:
        if not isinstance(value, TicketSection):
            raise TicketContractError("sections должны содержать TicketSection")
        attributes = tuple(value.attributes)
        if len(attributes) > 200:
            raise TicketContractError("TicketSection содержит больше 200 attributes")
        documents = [self._attribute(item) for item in attributes]
        keys = [item["key"] for item in documents]
        if len(keys) != len(set(keys)):
            raise TicketContractError(
                "TicketSection.attributes должны иметь уникальные key"
            )
        return {
            "id": _identifier(value.section_id, name="TicketSection.section_id"),
            "title": _text(
                value.title, name="TicketSection.title", limit=500, required=True
            ),
            "attributes": documents,
        }

    def _attribute(self, value: Any) -> dict[str, Any]:
        if not isinstance(value, TicketAttribute):
            raise TicketContractError(
                "attributes должны содержать TicketAttribute"
            )
        kind = str(value.kind).strip().casefold()
        if kind not in _ATTRIBUTE_KINDS:
            raise TicketContractError(f"Неизвестный TicketAttribute.kind {kind!r}")
        url = _text(value.url, name="TicketAttribute.url", limit=4_096)
        if url:
            parsed = urlsplit(url)
            if not (url.startswith("/") or parsed.scheme in {"http", "https"}):
                raise TicketContractError(
                    "TicketAttribute.url должен быть same-origin или HTTP(S) URL"
                )
        return {
            "key": _identifier(value.key, name="TicketAttribute.key"),
            "label": _text(
                value.label, name="TicketAttribute.label", limit=500, required=True
            ),
            "value": _json_safe(value.value),
            "kind": kind,
            "url": url,
            "copyable": bool(value.copyable),
            "tone": self._tone(value.tone),
        }

    def _action_document(self, value: Any) -> dict[str, Any]:
        if not isinstance(value, TicketAction):
            raise TicketContractError("actions должны содержать TicketAction")
        if not callable(value.handler):
            raise TicketContractError("TicketAction.handler должен быть callable")
        style = str(value.style).strip().casefold()
        if style not in _ACTION_STYLES:
            raise TicketContractError(f"Неизвестный TicketAction.style {style!r}")
        color = _text(value.color, name="TicketAction.color", limit=7)
        if color and not _COLOR.fullmatch(color):
            raise TicketContractError(
                "TicketAction.color должен быть hex-цветом #RGB или #RRGGBB"
            )
        return {
            "id": _identifier(value.action_id, name="TicketAction.action_id"),
            "label": _text(
                value.label, name="TicketAction.label", limit=300, required=True
            ),
            "description": _text(
                value.description, name="TicketAction.description", limit=2_000
            ),
            "style": style,
            "color": color,
            "confirmation_required": bool(value.confirmation_text),
            "disabled_reason": _text(
                value.disabled_reason,
                name="TicketAction.disabled_reason",
                limit=2_000,
            ),
        }

    def _card_version(self, value: TicketCard) -> str:
        shape = {
            "id": str(value.ticket_id),
            "status": str(value.status),
            "updated_at": str(value.updated_at),
            "sections": [self._section(item) for item in value.sections],
            "actions": [self._action_document(item) for item in value.actions],
        }
        encoded = json.dumps(
            shape, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()[:20]

    @staticmethod
    def _action_result(value: Any) -> TicketActionResult:
        if value is None:
            return TicketActionResult()
        if isinstance(value, TicketActionResult):
            return value
        if isinstance(value, Mapping):
            unknown = set(value) - {"message", "data", "reload_card"}
            if unknown:
                raise TicketContractError(
                    "Ticket action result содержит неизвестные поля: "
                    + ", ".join(sorted(str(item) for item in unknown))
                )
            return TicketActionResult(
                message=str(value.get("message") or "Действие выполнено"),
                data=value.get("data"),
                reload_card=bool(value.get("reload_card", True)),
            )
        return TicketActionResult(data=value)

    @staticmethod
    def _tone(value: Any) -> str:
        tone = str(value or "default").strip().casefold()
        return tone if tone in _TONES else "default"
