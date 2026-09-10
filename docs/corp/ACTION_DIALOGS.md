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
- `message` и optional `data`;
- `close_dialog`; если `None`, действует `close_on_success` кнопки.

Каждый patch повторно нормализуется Python runtime. Неизвестные поля не
попадают в браузер. Для опасной операции задайте `confirmation_text`: public
runtime выдаст и проверит одноразовый confirmation token.

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

- `field` — ключ соседнего поля этого же объекта/блока;
- `parameter` — имя в `extra_params`; по умолчанию равно `field`;
- `item_field` — взять атрибут полного выбранного reference item, а не его
  сохранённый `value_key`.

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
10. отсутствие secret/необъявленных значений в handler и server log.
