# Корпоративные формы

## Контракт формы

Корпоративная форма наследуется от public `BaseForm`. Она описывает доменную
операцию, но не создаёт UI:

```python
from typing import Any

from forms.base_form import BaseForm, ServerAction
from forms.fields import FieldDefinition, FieldType, ReferenceConfig


class CreateApiForm(BaseForm):
    form_id = "api.create"
    title = "Создание API"
    category = "api"
    description = "Создание и регистрация нового API в Gravitee"

    @property
    def fields(self) -> list[FieldDefinition]:
        return [
            FieldDefinition(
                key="name",
                label="Название API",
                field_type=FieldType.TEXT,
                placeholder="Например, Orders.Public",
            ),
            FieldDefinition(
                key="context_path",
                label="Context path",
                field_type=FieldType.TEXT,
            ),
        ]

    def validate(self, form_data: dict[str, Any]):
        errors = super().validate(form_data)
        path = str(form_data.get("context_path", ""))
        if path and not path.startswith("/"):
            errors.append(self.validation_error(
                "context_path", "Context path должен начинаться с /"
            ))
        return errors

    def build_payload(self, form_data: dict[str, Any]) -> dict[str, Any]:
        return {
            "name": form_data["name"],
            "contextPath": form_data["context_path"],
        }

    def get_submit_endpoint(self, environment: str) -> str:
        return self.gravitee_service.create_api_url(environment)
```

Обязательны `form_id`, `title`, `category`, `fields`, `build_payload()` и
`get_submit_endpoint()`. `description` показывается в web-каталоге; если оно
пустое, frontend ничего не дорисовывает.

`form_id` и field keys — persistent API identifiers. Их изменение ломает drafts,
history, AI routing и внешних клиентов. Для переименования пользовательской
подписи меняйте `title`/`label`, а не ID.

## Поля

| `FieldType` | Python value | Назначение |
|---|---|---|
| `TEXT` | `str` | одна строка |
| `TEXTAREA` | `str` | многострочный текст |
| `NUMBER` | `int` или `float` | конечное число |
| `CHECKBOX` | `bool` | переключатель |
| `SELECT` | один `ReferenceConfig.value_key` | одиночный справочник |
| `MULTISELECT` | `list[value_key]` | множественный справочник |
| `FILE` | `str` | содержимое выбранного файла/ручной ввод |
| `BLOCK` | `dict` | вложенная группа `block_fields` |

Основные параметры `FieldDefinition`:

- `required`, `default`, `placeholder`, `hint`;
- `reference` для `SELECT`/`MULTISELECT`;
- `condition(values) -> bool` для server-side visibility;
- `plural=True` и optional `plural_max` для повторяемого поля;
- `block_fields` для вложенной структуры;
- `depends_on`/`depends_on_field` для зависимого справочника.

`width` сохранён для desktop compatibility; web-формы отображаются вертикально
и не должны кодировать бизнес-смысл шириной виджета.

### Условные поля

Runtime вычисляет condition при первой загрузке и после каждого изменения. В
этот момент словарь может быть неполным, поэтому прямой индекс запрещён:

```python
# правильно
condition=lambda values: not bool(values.get("create_application", False))

# неправильно: KeyError на начальном состоянии
condition=lambda values: not values["create_application"]
```

Скрытое условное поле удаляется из нормализованных values до validation и
payload. Не задавайте ему искусственный `False`, если тип поля не `CHECKBOX`.

Для поля внутри `BLOCK` condition получает values этого блока. Controlling field
должно находиться на том же уровне.

### Повторяемые поля и блоки

При `plural=True` runtime использует ключи `key`, `key_2`, `key_3` и далее.
Собирать непустые значения следует public helper:

```python
methods = self.collect_plural(form_data, "method")
```

Plural `BLOCK` хранит отдельный dict в каждом instance. Не разбирайте suffixes
вручную, если достаточно `collect_plural`.

## Валидация

Generic runtime сначала приводит типы, отбрасывает неизвестные/скрытые поля,
проверяет required и reference IDs, затем вызывает domain `validate()`.

```python
def validate(self, form_data):
    errors = super().validate(form_data)
    if form_data.get("min_replicas", 0) > form_data.get("max_replicas", 0):
        errors.append(self.validation_error(
            "max_replicas",
            "Максимум не может быть меньше минимума",
            code="replica_range",
        ))
    return errors
```

`self.validation_error()` гарантирует inline message и focus. Простые строки
поддерживаются для совместимости, но привязка по тексту не гарантируется.
Validation не выполняет сетевой write и не изменяет форму.

## ServerAction вместо UI callback

Дополнительная кнопка web-формы описывается серверным action:

```python
def get_server_actions(self):
    return [ServerAction(
        action_id="load_swagger_methods",
        label="Подтянуть методы из Swagger",
        handler=self._load_swagger_methods,
        style="Secondary",
        require_valid_form=True,
        confirmation_text="Загрузить методы из указанного Swagger?",
    )]

def _load_swagger_methods(self, environment, form_data):
    methods = self.gravitee_service.read_swagger_methods(
        environment, form_data["swagger_url"]
    )
    return {
        "message": f"Найдено методов: {len(methods)}",
        "values": {"methods": methods},
        "data": {"count": len(methods)},
    }
```

Контракт handler: `(environment: str, form_data: dict) -> mapping | None`.
Допустимые result keys: `message`, `values`, `data`. `values` проходит через
normalization/state на сервере, затем применяется frontend.

`confirmation_text` включает one-use confirmation token. `require_valid_form`
запрещает action до успешной validation. Action errors показываются рядом с
операцией и логируются server-side.

Legacy `CustomButton` остаётся только для Tkinter. Он отображается disabled в web
и не должен использоваться для новой функциональности. Кастомные диалоги нужно
выразить как поля формы, confirmation или параметры отдельного `ServerAction`.

## Загрузка заявки

Чтобы показать общую кнопку заявки:

```python
@property
def itsm_support(self) -> bool:
    return True

def fetch_from_itsm(self, environment: str, ticket_id: str):
    ticket = self.itsm_service.get_ticket(ticket_id, environment)
    return {
        "name": ticket.get("service_name", ""),
        "description": ticket.get("summary", ""),
    }
```

Метод должен вернуть patch `{field_key: value}`. Неизвестные keys игнорируются.
Ошибку получения заявки нужно выбросить: frontend покажет её в окне операции,
не меняя форму частично.

## Submit lifecycle

```text
state/normalize
  -> generic + domain validate
  -> preview: build_payload + confirmation document
  -> explicit user confirmation when configured
  -> submit: repeat validation
  -> select auth
  -> build_payload
  -> pre_submit(form_data, payload, environment)
  -> HTTP POST/PUT
  -> result and optional polling hooks
```

Форма может переопределить:

- `get_http_method()` — только `POST` или `PUT`;
- `get_submit_headers(environment)` — дополнительные non-secret headers;
- `get_auth_type()` — `gravitee`, `tfs`, `itsm` или `none`;
- `confirm_submit()` и `build_confirm_text(...)`;
- `pre_submit(form_data, payload, environment)` — mutate уже построенный payload
  или остановить submit исключением;
- `get_result_config()`, `get_result_status()`, `build_result_content()`;
- `get_poll_endpoint()`, `get_poll_status()`, `build_poll_content()`,
  `should_continue_polling()` и post-poll info hooks.

`pre_submit()` не должен повторно отправлять основной HTTP request. Если он
выбрасывает исключение, submit завершается ошибкой, а пользователь может
исправить данные и повторить попытку с новым confirmation token.

Auth устанавливает public `SubmitService`; подробности — в
[SERVICES_AND_ENVIRONMENT.md](SERVICES_AND_ENVIRONMENT.md).

## Доступ к окружению и selected reference items

Используйте `environment` из аргумента hook либо `self.current_environment`:

```python
def validate(self, form_data):
    environment = self.current_environment
    ...
```

Каждый web request работает с отдельной runtime-копией формы. Не сохраняйте
request state в class/global attributes.

Полный item выбранного справочника доступен только там, где runtime успел
разрешить references:

```python
def pre_submit(self, form_data, payload, environment):
    api = self.screen.get_field_item("api")
    ingresses = self.screen.get_field_items("ingresses")
```

| Вызов | Web support | Рекомендация |
|---|---|---|
| `self.current_environment` | во всех form hooks | основной способ |
| `self.screen.app.current_environment.get()` | нет | заменить |
| `self.screen.get_field_item(s)` | `pre_submit`, `ServerAction` | использовать только для полного reference item |
| `self.apply_form_data()` | `ServerAction`, `fetch_from_itsm` | лучше явно вернуть `values` |
| `self.screen.apply_form_data()` | те же два hook, compatibility | заменить на явный result |
| Tkinter widget/dialog methods | нет | выразить через schema/action/confirmation |

В `fields`, `validate`, `build_payload` и preview нельзя полагаться на
`self.screen`: используйте только values и public services.

## Проверка формы

Для каждой формы покройте:

- metadata и уникальность `form_id`;
- defaults и initial visibility;
- каждую ветвь condition;
- type coercion, required и domain errors с field path;
- SELECT/MULTISELECT IDs и dependent references;
- точный preview payload;
- endpoint, method, auth type и headers для каждого environment;
- `pre_submit` mutation/error;
- каждый ServerAction, ITSM patch и confirmation;
- result/poll termination.

В integration smoke test запросите form document, отправьте initial `/state`,
`/validate` и `/preview`. Реальный write проверяйте только на разрешённом test
endpoint или через fake HTTP adapter.
