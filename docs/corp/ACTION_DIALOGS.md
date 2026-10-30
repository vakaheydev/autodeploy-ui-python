# Интерактивные действия и диалоги формы

## Когда нужен диалог

Обычный `ServerAction` подходит, если одной кнопке достаточно текущих значений
формы и результат можно получить одним вызовом Python handler. Используйте
`ServerActionDialog`, если перед действием оператор должен:

- выбрать дополнительные значения, не являющиеся постоянными полями формы;
- загрузить файл;
- выбрать один или несколько элементов справочника;
- последовательно нажать несколько серверных кнопок, не закрывая окно;
- перенести результат обратно в основную форму.

Диалог не является private React-компонентом. Корпоративная форма объявляет его
Python-контрактом, public React renderer показывает те же `FieldDefinition`, а
вся загрузка данных, валидация и обработка кнопок остаются на Python-сервере.

## Кнопки непосредственно под полем

В основной web-форме `FieldDefinition.actions` принимает последовательность
`FieldAction`. Кнопки отображаются под соответствующим полем, включая вложенные
блоки и конкретные повторяемые экземпляры (`target_2`, `block_2.value`).
Идентификаторы кнопок уникальны **внутри одного поля**. Старые footer actions
и Tkinter-кнопки сохраняют прежний контракт; новые field actions относятся к web UI.

Все новые типы импортируются из `forms.field_actions`:

```python
from forms.field_actions import (
    FieldAction, FieldActionContext, FieldActionDialog, FieldDialogAction,
)
from forms.fields import FieldDefinition, FieldType, ReferenceConfig
from forms.base_form import ServerActionResult, ServerDialogActionResult


def apply_categories(ctx: FieldActionContext):
    # Полные записи, а не только идентификаторы выбранных пунктов.
    items = ctx.get_selected_items("categories")
    text = "\n".join(item["name"] for item in items)
    ctx.set_value(text)
    return ServerDialogActionResult(message="Категории подставлены")


description_field = FieldDefinition(
    key="description",
    label="Описание",
    field_type=FieldType.TEXTAREA,
    actions=(FieldAction(
        action_id="choose_categories",
        label="Выбрать категории",
        dialog=FieldActionDialog(
            title="Категории для описания",
            fields=(FieldDefinition(
                key="categories",
                label="Категории",
                field_type=FieldType.MULTISELECT,
                reference=ReferenceConfig(
                    source="local",
                    resource="api_categories.json",
                    value_key="id",
                    label_key="name",
                ),
            ),),
            actions=(FieldDialogAction(
                action_id="apply", label="Подставить", handler=apply_categories,
            ),),
        ),
    ),),
)
```

При нажатии открывается обычный серверный диалог. Справочник поддерживает поиск,
множественный выбор, обновление и просмотр записей. Для HTTP-справочника укажите
его `ReferenceConfig`; загрузка пройдёт через зарегистрированные Python handlers.
`apply_categories` вызывается **после** выбора и нажатия «Подставить», получает
выбор и устанавливает значение ровно того экземпляра поля, откуда открыли окно.
Это двухэтапное взаимодействие через HTTP, не блокирующий вызов Tkinter/modal.

Для кнопки без окна задайте `FieldAction(handler=callback)`. Callback получает
один `FieldActionContext` и может вернуть `ServerActionResult` или `None`:

```python
def fill_from_reference(ctx: FieldActionContext):
    records = ctx.load_reference(ReferenceConfig("local", "api_categories.json"))
    ctx.set_value("; ".join(item["name"] for item in records))
    return ServerActionResult(message="Поле заполнено")

button = FieldAction("fill", "Заполнить из справочника", handler=fill_from_reference)
```

Контекст обработчика:

| Член | Назначение |
|---|---|
| `environment: str` | Выбранное рабочее окружение |
| `field_path: str`, `field: FieldDefinition` | Точный путь экземпляра и его Python-описание |
| `value` | Текущее значение поля |
| `form_values: dict` | Нормализованный снимок основной формы |
| `dialog_values: dict` | Нормализованные значения окна; `{}` у прямой кнопки |
| `http` | Штатный `core.http_client.HttpClient` для `get/post/put/...` |
| `services` | Сервисы установленного provider: `.itsm`, `.tfs`, `.gravitee` |
| `load_reference(reference, *, extra_params=None)` | Загрузить полные записи через штатные обработчики и кэш текущего окружения |
| `get_selected_items(key)` | Полные выбранные записи в обработчике; поля диалога имеют приоритет над одноимёнными полями формы |
| `set_value(value)` | Установить значение текущего поля с серверной нормализацией, сохранив соседние поля |

Для произвольного HTTP вызовите, например, `ctx.http.get(url)` внутри callback.
Доменную интеграцию и credentials держите в private services. Не выполняйте I/O
в `fields`, при конструировании `FieldAction` или `FieldActionDialog`: эти описания
читаются при построении схемы и версии формы.

`FieldAction` объявляет ровно один `handler` или `dialog`. Дополнительные параметры:
`style="Secondary"`, `require_valid_form=False`, `confirmation_text=""`.
Для диалога подтверждение задаётся на конкретном `FieldDialogAction`, а не на
открывающей кнопке. `FieldDialogAction` принимает `handler(context)`,
`style="Primary"`, `require_valid_dialog=True`, `confirmation_text=""`,
`close_on_success=True`. Возвращаемый `ServerDialogActionResult` поддерживает
сообщение, статус, патч значений окна и `close_dialog`, как у footer-диалогов.

`FieldActionDialog.initial_values` — mapping или callback `(context) -> mapping`,
вызываемый при открытии. `validate(context)` возвращает те же ошибки, что обычный
валидатор диалога; он должен быть read-only. `set_value` разрешён только внутри
обработчиков кнопок. При исключении или `ResultStatus.ERROR` значение, переданное
через `set_value`, не применяется. При успешном ответе поле получает обновление,
а ручной черновик сохраняется обычным механизмом формы.

Зависимые справочники окна используют прежний `ReferenceDependency`, включая
`scope="form"`; это не передаёт справочнику всю форму. Внутри окон используйте
`FieldDialogAction`: вложенные `FieldDefinition.actions` в диалоге не поддерживаются.
Сервер отклоняет вызовы для скрытого или удалённого экземпляра, устаревшую версию
формы и подтверждение, полученное для другого поля/значений.

REST использует существующие `/forms/{form_id}/actions/{action_id}` и `.../dialog`
маршруты с дополнительным `owner_field_path` в body. Его нужно передавать при
открытии, пересчёте, загрузке справочника и выполнении кнопки. При пустом пути
сохраняется обычное поведение footer action. Ответ окна сохраняет `owner_field_path`.
Callables, HTTP-клиент и service objects никогда не попадают в JSON схемы.

## Контракты

```python
from forms.base_form import (
    ServerAction,
    ServerActionDialog,
    ServerDialogAction,
    ServerDialogActionResult,
)
from forms.fields import (
    FieldDefinition,
    FieldType,
    ReferenceConfig,
    ReferenceDependency,
)
from forms.result_config import ResultStatus
```

`ServerAction` объявляет либо прежний `handler`, либо `dialog`, но не оба сразу.
Существующие actions с handler менять не требуется.

```python
ServerAction(
    action_id="choose_swagger_methods",
    label="Выбрать методы из Swagger",
    dialog=ServerActionDialog(...),
)
```

`ServerActionDialog` принимает:

- `title` и optional `description`;
- `fields` — обычные `FieldDefinition`, включая `FILE`, `SELECT`,
  `MULTISELECT`, условные и вложенные `BLOCK`;
- `actions` — одну или несколько Python-кнопок `ServerDialogAction`;
- `initial_values` — mapping либо callback
  `(environment, form_values) -> mapping`;
- optional `validate(environment, form_values, dialog_values)` с теми же
  форматами ошибок, что у `BaseForm.validate()`.

Handler кнопки имеет сигнатуру:

```python
handler(
    environment: str,
    form_values: dict,
    dialog_values: dict,
) -> ServerDialogActionResult | mapping | None
```

Он может вернуть:

- `form_values` — partial patch основной формы;
- `dialog_values` — partial patch открытого диалога;
- `message`, `status`, `title` и optional `data`;
- `close_dialog`; если `None`, действует `close_on_success` кнопки, кроме
  `ResultStatus.ERROR`: штатная ошибка по умолчанию оставляет окно открытым.

Каждый patch повторно нормализуется Python runtime. Неизвестные поля не
попадают в браузер. Для опасной операции задайте `confirmation_text`: public
runtime выдаст и проверит одноразовый confirmation token.

## Статусы результата

Не возвращайте текст ошибки как обычное успешное сообщение. Для ожидаемой
ошибки интеграции, отсутствующих данных или отклонённой бизнес-операции верните:

```python
return ServerDialogActionResult(
    status=ResultStatus.ERROR,
    title="Swagger не прочитан",
    message="TFS не вернул описание Swagger для выбранного API",
)
```

Поддерживаются `ResultStatus.SUCCESS`, `ERROR`, `WAITING`, `PENDING`. Поле
`status` определяет оформление сообщения, но не HTTP-код. Исключение Python
оставляйте для неожиданной технической ошибки; runtime безопасно преобразует
его в API error и залогирует причину. Старый результат без `status` считается
`SUCCESS`.

При `ERROR` диалог остаётся открытым, чтобы пользователь видел причину и мог
исправить ввод. Явный `close_dialog=True` закрывает его; тогда красная карточка
показывается в форме, а frontend автоматически прокручивает и переводит фокус
к этой карточке.

## Доступ к значениям основной формы

Диалог не изолирован от своей формы. Public runtime передаёт актуальный
нормализованный снимок основной формы во все серверные callbacks:

- `initial_values(environment, form_values)`;
- `validate(environment, form_values, dialog_values)`;
- `ServerDialogAction.handler(environment, form_values, dialog_values)`.

Например, кнопка может прочитать `form_values["api"]` и вернуть patch другого
поля через `ServerDialogActionResult(form_values={...})`. Значения являются
копиями: изменение словаря аргумента само по себе не изменяет открытую форму.

Справочник внутри диалога вызывается отдельно от button handler. Чтобы дать
его corporate `BaseReferenceHandler` доступ к конкретному полю основной формы,
объявите это поле в `ReferenceDependency` с `scope="form"`:

```python
FieldDefinition(
    key="methods",
    label="Методы Swagger",
    field_type=FieldType.MULTISELECT,
    reference=ReferenceConfig(
        source="corp_swagger",
        resource="swagger_methods",
        value_key="operation_id",
        label_key="display_name",
        required_params=("api_id", "swagger_document"),
    ),
    reference_dependencies=(
        # Поле api находится в самом диалоге.
        ReferenceDependency(
            field="api",
            parameter="api_id",
            item_field="id",
        ),
        # swagger_file находится в основной форме.
        ReferenceDependency(
            field="swagger_file",
            parameter="swagger_document",
            scope="form",
        ),
    ),
)
```

Значения `scope`:

- `"current"` — значение соседнего поля диалога; используется по умолчанию и
  полностью совместимо с прежним контрактом;
- `"form"` — значение корневого поля формы, которой принадлежит диалог.

Для reference-поля основной формы можно одновременно задать `item_field`:
runtime разрешит сохранённый ID через справочник формы и передаст handler нужное
поле полного объекта. Например:

```python
ReferenceDependency(
    "api",
    parameter="context_path",
    item_field="context_path",
    scope="form",
)
```

Доступ остаётся явным и минимальным: reference handler получает в
`extra_params` только перечисленные зависимости, а не полный `form_values`.
Это позволяет использовать поля формы, не раскрывая справочнику остальные
значения, FILE-контент или секретные поля.

## Несколько зависимостей справочника

Legacy `depends_on="api"` и `depends_on_field="id"` поддерживаются без
изменений. Для двух и более входов используйте явный allowlist
`reference_dependencies`:

```python
FieldDefinition(
    key="methods",
    label="Методы Swagger",
    field_type=FieldType.MULTISELECT,
    reference=ReferenceConfig(
        source="corp_swagger",
        resource="swagger_methods",
        value_key="operation_id",
        label_key="display_name",
        search_keys=("display_name", "path", "http_method"),
        required_params=("api_id", "source"),
    ),
    reference_dependencies=(
        ReferenceDependency(
            field="api",
            parameter="api_id",
            item_field="id",
        ),
        ReferenceDependency(
            field="swagger_source",
            parameter="source",
        ),
        ReferenceDependency(
            field="swagger_environment",
            parameter="swagger_environment",
        ),
        ReferenceDependency(
            field="swagger_file",
            parameter="swagger_document",
        ),
    ),
)
```

У каждой зависимости:

- `field` — ключ поля выбранного scope;
- `parameter` — имя в `extra_params`; по умолчанию равно `field`;
- `item_field` — взять атрибут полного выбранного reference item, а не его
  сохранённый `value_key`.
- `scope` — `"current"` для соседнего поля или `"form"` для корневого поля
  основной формы внутри `ServerActionDialog`.

Для `FILE` отдельный `item_field` не нужен: handler получает
нормализованное содержимое файла. Runtime никогда не передаёт handler весь
`form_state`; только перечисленные зависимости. Не включайте секретное поле в
этот allowlist.

Если любой ключ из `ReferenceConfig.required_params` отсутствует или пуст,
resolver не вызывается и список остаётся пустым. Необязательная зависимость
может присутствовать в `reference_dependencies`, но отсутствовать в
`required_params`.

## Полный пример: выбрать методы Swagger

```python
class AddSubscriptionMethodsForm(BaseForm):
    # form_id/title/category/fields/build_payload/... опущены

    def get_server_actions(self):
        return [ServerAction(
            action_id="choose_swagger_methods",
            label="Выбрать методы из Swagger",
            style="Secondary",
            dialog=ServerActionDialog(
                title="Выбор методов из Swagger",
                description=(
                    "Выберите источник Swagger, затем отметьте методы, "
                    "которые нужно перенести в подписку."
                ),
                fields=(
                    FieldDefinition(
                        key="api",
                        label="API",
                        field_type=FieldType.SELECT,
                        reference=ReferenceConfig(
                            source="corp_http",
                            resource="gravitee_apis",
                            value_key="id",
                            label_key="name",
                            search_keys=("context_path", "name", "id"),
                            detail_keys=("id", "name", "context_path"),
                        ),
                    ),
                    FieldDefinition(
                        key="swagger_source",
                        label="Источник Swagger",
                        field_type=FieldType.SELECT,
                        reference=ReferenceConfig(
                            source="corp_local",
                            resource="swagger_sources.json",
                            value_key="id",
                            label_key="name",
                        ),
                    ),
                    FieldDefinition(
                        key="swagger_environment",
                        label="Окружение источника",
                        field_type=FieldType.SELECT,
                        required=False,
                        reference=ReferenceConfig(
                            source="corp_local",
                            resource="swagger_environments.json",
                            value_key="id",
                            label_key="name",
                        ),
                        condition=lambda values: (
                            values.get("swagger_source") == "repository"
                        ),
                    ),
                    FieldDefinition(
                        key="swagger_file",
                        label="Swagger-файл",
                        field_type=FieldType.FILE,
                        required=False,
                        file_type=".json",
                        condition=lambda values: (
                            values.get("swagger_source") == "file"
                        ),
                    ),
                    FieldDefinition(
                        key="methods",
                        label="Методы",
                        field_type=FieldType.MULTISELECT,
                        reference=ReferenceConfig(
                            source="corp_swagger",
                            resource="swagger_methods",
                            value_key="operation_id",
                            label_key="display_name",
                            search_keys=(
                                "display_name", "path", "http_method",
                            ),
                            required_params=("api_id", "source"),
                        ),
                        reference_dependencies=(
                            ReferenceDependency(
                                "api", parameter="api_id", item_field="id"
                            ),
                            ReferenceDependency(
                                "swagger_source", parameter="source"
                            ),
                            ReferenceDependency("swagger_environment"),
                            ReferenceDependency(
                                "swagger_file", parameter="swagger_document"
                            ),
                        ),
                    ),
                    FieldDefinition(
                        key="status",
                        label="Результат проверки",
                        field_type=FieldType.TEXTAREA,
                        required=False,
                    ),
                ),
                actions=(
                    ServerDialogAction(
                        action_id="inspect",
                        label="Проверить Swagger",
                        handler=self._inspect_swagger,
                        style="Secondary",
                        require_valid_dialog=False,
                        close_on_success=False,
                    ),
                    ServerDialogAction(
                        action_id="apply",
                        label="Применить",
                        handler=self._apply_methods,
                        style="Primary",
                        confirmation_text="Перенести выбранные методы в форму?",
                    ),
                ),
                initial_values=lambda environment, _form_values: {
                    "swagger_environment": environment,
                },
                validate=self._validate_method_dialog,
            ),
        )]

    def _validate_method_dialog(
        self,
        _environment,
        _form_values,
        dialog_values,
    ):
        if not dialog_values.get("methods"):
            return [self.validation_error(
                "methods", "Выберите хотя бы один метод"
            )]
        return []

    def _inspect_swagger(self, environment, form_values, dialog_values):
        # Read-only проверка остаётся в corporate Python service/handler.
        return ServerDialogActionResult(
            message="Swagger прочитан",
            dialog_values={"status": "Источник доступен"},
            close_dialog=False,
        )

    def _apply_methods(self, environment, form_values, dialog_values):
        return ServerDialogActionResult(
            message="Методы перенесены в форму",
            form_values={"methods": dialog_values["methods"]},
        )
```

`ServerDialogActionResult` также принимает `status: ResultStatus` и `title`.
Если обработчик возвращает `ResultStatus.ERROR` и явно не задаёт
`close_dialog`, окно остаётся открытым, а ошибка показывается внутри него. Если
`close_dialog=True` задан явно, диалог закрывается и основная форма
автоматически прокручивается к красной карточке результата. Mapping-форма
поддерживает ключи `status` и `title` по тем же правилам.

Corporate `BaseReferenceHandler.load()` для `corp_swagger` получает только
объявленные значения:

```python
def load(self, config, environment="", extra_params=None):
    params = extra_params or {}
    if config.resource != "swagger_methods":
        return []
    return self.swagger_service.list_methods(
        environment=environment,
        api_id=params.get("api_id", ""),
        source=params.get("source", ""),
        swagger_environment=params.get("swagger_environment", ""),
        swagger_document=params.get("swagger_document", ""),
    )
```

## HTTP flow

```text
operator clicks form action
  -> POST /forms/{form}/actions/{action}/dialog
  -> React renders server-owned dialog document
  -> POST .../dialog/state after field changes
  -> POST .../dialog/fields/{path}/options for a reference
  -> Python resolves only declared ReferenceDependency values
     from dialog fields and explicitly allowed owning-form fields
  -> operator clicks a dialog button
  -> POST .../dialog/actions/{button}
  -> Python validation + optional confirmation + handler
  -> form_values/dialog_values patches
```

Закрытие окна без успешной кнопки не изменяет основную форму. Ни один dialog
action автоматически не отправляет форму: обычные preview, validation и submit
остаются отдельной явной операцией пользователя.

## Ограничения и правила

- Не открывайте Tkinter dialog из `ServerDialogAction`.
- Не возвращайте callable, URL, auth header или secret в result.
- Не сохраняйте request state в атрибутах экземпляра формы: runtime создаёт
  request-scoped копию.
- Side effect выполняйте только в явно названной кнопке и защищайте
  `confirmation_text`, если действие опасно.
- `initial_values` и `dialog_values` должны содержать только ключи dialog fields.
- Полный выбранный item доступен в button handler через
  `self.screen.get_field_item("api")`; основной способ — всё равно принимать
  нормализованные scalar/list values из аргументов.
- Один `ServerActionDialog` принадлежит одной форме. Для самостоятельной
  сложной страницы используйте `PluginDefinition`, а не action dialog.

## Тесты корпоративной формы

Покройте минимум:

1. action помечен как dialog в form document;
2. initial values и первая видимость conditional fields;
3. отсутствие вызова resolver при пустом required dependency;
4. точный `extra_params` для каждого источника Swagger;
5. SELECT scalar и MULTISELECT list;
6. inline error custom validator;
7. keep-open button и его `dialog_values` patch;
8. confirmation token опасной кнопки;
9. итоговый `form_values` patch и отсутствие submit;
10. точные `scope="form"` зависимости и отсутствие прочих значений формы в
    `extra_params` reference handler;
11. отсутствие secret/необъявленных значений в handler и server log.
