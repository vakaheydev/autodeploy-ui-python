# Корпоративные плагины (custom pages)

## Когда нужен плагин

Плагин — это отдельная рабочая страница в разделе **Плагины**, определённая
целиком в private Python package. Используйте его для отчёта, мастера,
диагностической панели или корпоративной операции, которая не является обычным
submit одной формы.

Плагин не является frontend-расширением: private package не поставляет React,
JavaScript или HTML. Он объявляет поля, операции и динамические виджеты через
публичные Python-контракты. Public React-клиент отображает полученный документ
универсально. Благодаря этому корпоративный код имеет доступ к сервисам, но
секреты и callable никогда не пересекают API-границу.

```text
corp PluginDefinition
  -> PluginRuntime (environment, defaults, conditions, references, validation)
  -> /api/v1/plugins/*
  -> generic React renderer

button / AI operation
  -> Python PluginOperation.handler(PluginContext, normalized_values)
  -> corporate services
  -> PluginActionResult
  -> updated values + widgets
```

Обычная форма остаётся правильным выбором, если нужен стандартный жизненный
цикл `validate -> preview -> confirm -> submit -> history`. Не превращайте форму
в плагин только ради другой раскладки.

## Точка подключения

Рекомендуемая структура private package:

```text
src/corp_autodeploy/
├── plugins/
│   ├── __init__.py
│   ├── registrar.py
│   └── capacity_report.py
├── services.py
├── references.py
└── reference_data/
```

В `.env` укажите публичный extension point и перезапустите Python server:

```dotenv
AUTODEPLOY_PLUGIN_REGISTRAR=corp_autodeploy.plugins.registrar:register_plugins
```

Registrar принимает `PluginRegistry` и не возвращает значение:

```python
from plugins import PluginRegistry

from corp_autodeploy.plugins.capacity_report import CAPACITY_REPORT


def register_plugins(registry: PluginRegistry) -> None:
    registry.register(CAPACITY_REPORT)
```

`plugin_id` — стабильный lowercase identifier (`a-z`, цифры, `.`, `_`, `-`) до
80 символов. Не меняйте его после выпуска: он входит в URL, AI policy и имя MCP
tool. Поля одного плагина и его `operation_id` должны быть уникальны.

## Полный минимальный плагин

```python
from typing import Any, Mapping

from forms.base_form import FormValidationIssue
from forms.fields import FieldDefinition, FieldType, ReferenceConfig
from plugins import (
    ChartSeries,
    ChartWidget,
    MetricWidget,
    PluginActionResult,
    PluginContext,
    PluginDefinition,
    PluginOperation,
    TableWidget,
    TextWidget,
)


FIELDS = (
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
            detail_keys=("id", "name", "context_path", "owner"),
        ),
    ),
    FieldDefinition(
        key="include_plans",
        label="Показывать планы",
        field_type=FieldType.CHECKBOX,
        required=False,
        default=True,
    ),
)


def validate_page(
    context: PluginContext,
    values: Mapping[str, Any],
) -> list[FormValidationIssue]:
    if values.get("api") == "forbidden-id":
        return [FormValidationIssue("api", "Этот API недоступен для отчёта")]
    return []


def render_page(
    context: PluginContext,
    values: Mapping[str, Any],
):
    # render вызывается при открытии и после изменения значений. Он должен быть
    # read-only, быстрым и детерминированным для одного состояния.
    api_id = str(values.get("api") or "")
    if not api_id:
        return [TextWidget(
            "hint",
            "Выберите API, чтобы построить отчёт.",
            tone="info",
        )]

    report = context.services.gravitee.get_capacity_report(
        context.environment,
        api_id,
    )
    return [
        MetricWidget(
            "total-rps",
            "Текущий RPS",
            report["rps"],
            detail="Среднее за пять минут",
        ),
        ChartWidget(
            "rps-trend",
            title="Нагрузка",
            chart_type="area",
            labels=tuple(report["labels"]),
            series=(ChartSeries("RPS", tuple(report["values"])),),
            y_label="requests/sec",
        ),
        TableWidget(
            "top-routes",
            title="Самые нагруженные пути",
            columns=("Path", "RPS"),
            rows=tuple((row["path"], row["rps"]) for row in report["routes"]),
        ),
    ]


def refresh(
    context: PluginContext,
    values: Mapping[str, Any],
) -> PluginActionResult:
    context.services.gravitee.refresh_capacity_cache(
        context.environment,
        str(values["api"]),
    )
    return PluginActionResult(message="Данные обновлены")


CAPACITY_REPORT = PluginDefinition(
    plugin_id="reports.capacity",
    title="Нагрузка API",
    description="График и диагностические показатели нагрузки выбранного API.",
    category="Отчёты",
    keywords=("capacity", "rps", "нагрузка"),
    fields=FIELDS,
    validate=validate_page,
    render=render_page,
    operations=(
        PluginOperation(
            operation_id="refresh",
            label="Обновить данные",
            description="Сбрасывает корпоративный cache и перестраивает отчёт.",
            ai_description=(
                "Refresh capacity data only when the operator explicitly asks "
                "to reload this report."
            ),
            handler=refresh,
            style="primary",
            confirmation_text="Обновить данные из корпоративной системы?",
            require_valid_fields=True,
            read_only=False,
            idempotent=True,
            open_world=True,
        ),
    ),
)
```

## Поля

`PluginDefinition.fields` использует тот же `FieldDefinition`, что формы. Это
означает одинаковый UI и одинаковые Python semantics для всех типов:

| `FieldType` | Значение в `values` | Примечание |
|---|---|---|
| `TEXT` | `str` | Однострочное поле |
| `TEXTAREA` | `str` | Многострочный текст |
| `NUMBER` | `int`/`float` | Нормализуется Python runtime |
| `CHECKBOX` | `bool` | Не используйте строковые `"true"`/`"false"` |
| `FILE` | `str` | Содержимое выбранного файла, не путь клиента |
| `SELECT` | один `value_key` | Не label и не полный dictionary item |
| `MULTISELECT` | список `value_key` | Порядок сохраняется |
| `BLOCK` | object или массив instances | Поддерживает nested/conditional/reference fields |

Поддерживаются `required`, `default`, `placeholder`, `hint`, `condition`,
`plural`, `plural_max`, `block_fields`, `depends_on` и `depends_on_field`.
Condition всегда вычисляется на неполном состоянии, поэтому используйте
безопасный доступ:

```python
FieldDefinition(
    key="methods",
    label="Методы",
    field_type=FieldType.MULTISELECT,
    required=False,
    condition=lambda values: bool(values.get("load_methods")),
    reference=ReferenceConfig(
        source="corp_http",
        resource="api_methods",
        value_key="id",
        label_key="name",
        search_keys=("path", "method", "name"),
        required_params=("api",),
    ),
    depends_on="api",
    depends_on_field="id",
)
```

Справочники плагина проходят через тот же private handler, cache, поиск,
пагинацию, карточку по правому клику и server validation, что справочники форм.
Правила `value_key`, `search_keys`, dependent references и `detail_keys`
описаны в [REFERENCES_AND_SEARCH.md](REFERENCES_AND_SEARCH.md). Не загружайте
справочник вручную в `render`: объявите `ReferenceConfig`.

## PluginContext и корпоративные сервисы

Для каждого server request runtime создаёт новый `PluginContext`:

```python
context.environment       # выбранный environment key
context.env_manager       # чтение private server-side settings/secrets
context.http_client       # bounded public HTTP client
context.reference_resolver
context.services          # результат AUTODEPLOY_SERVICE_PROVIDER
```

В плагине используйте `context.services`, а не импорт глобального singleton.
Обычный provider возвращает `RuntimeServices(itsm=..., tfs=..., gravitee=...)`.
Private provider вправе вернуть свой объект с дополнительными typed services;
он всё равно остаётся server-side:

```python
from dataclasses import dataclass


@dataclass(frozen=True)
class CorporateServices:
    itsm: object
    tfs: object
    gravitee: object
    analytics: object


def create_services(env_manager, http_client):
    return CorporateServices(
        itsm=CorporateITSM(env_manager, http_client),
        tfs=CorporateTFS(env_manager, http_client),
        gravitee=CorporateGravitee(env_manager, http_client),
        analytics=CorporateAnalytics(env_manager, http_client),
    )
```

Не возвращайте service object или его raw response в `data/widgets`. Извлекайте
только безопасные display-данные. URL, auth headers и secrets остаются внутри
adapter. Подробнее: [SERVICES_AND_ENVIRONMENT.md](SERVICES_AND_ENVIRONMENT.md).

## Динамические виджеты

`render(context, values)` возвращает `PluginView`, sequence виджетов или
`None`. Доступны:

- `TextWidget` — пояснение/status с tone `default|info|success|warning|danger`;
- `MetricWidget` — число или короткий показатель;
- `ChartWidget` — `line`, `area`, `bar`, `pie`, `doughnut`;
- `TableWidget` — таблица до 50 колонок и 1000 строк;
- `ImageWidget` — server-generated PNG/JPEG/GIF/WebP.

Пример динамической картинки без temporary/public файла:

```python
from plugins import ImageWidget


png = context.services.analytics.build_topology_png(
    context.environment,
    values,
)
image = ImageWidget.from_bytes(
    "topology",
    png,
    mime_type="image/png",
    alt="Топология API и backend",
    title="Топология",
    caption="Построено по текущим параметрам",
)
```

Data image ограничен примерно 3 MB после base64. Inline SVG не принимается из-за
active-content risk. Числа графика должны быть finite; каждая series содержит
ровно столько значений, сколько `labels`; цвет задаётся CSS-именем или hex-кодом.
`pie/doughnut` принимает ровно одну series, где `labels` называют сектора.
`widget_id` уникален на странице.

`render` вызывается после открытия страницы и с debounce после изменения полей.
Не делайте в нём write, deploy или долгий многосистемный запрос. Для дорогого
расчёта используйте кнопку-операцию, верните готовые widgets и при необходимости
кэшируйте результат в корпоративном сервисе.

## Операции и кнопки

Каждый `PluginOperation` становится кнопкой. Handler исполняется только на
Python server и получает уже нормализованные visible values.

```python
def diagnose(context, values):
    result = context.services.analytics.diagnose(
        environment=context.environment,
        api_id=values["api"],
    )
    return PluginActionResult(
        message="Диагностика завершена",
        values={"last_run_id": result.run_id},       # partial patch
        widgets=(TextWidget("diagnosis", result.summary),),
        data={"run_id": result.run_id},              # для API client
    )
```

Handler может вернуть:

- `None` — стандартное успешное сообщение, затем повторный `render`;
- `PluginActionResult`;
- mapping с ключами только `message`, `values`, `widgets`, `data`;
- любое другое JSON-safe значение — оно попадёт в `data`.

`values` является patch, после которого runtime снова нормализует состояние.
Если `widgets=None`, вызывается `render` с обновлёнными values. Если операция
вернула widgets явно, они показываются немедленно.

Параметры операции:

- `require_valid_fields=True` — не запускать handler при ошибке полей;
- `confirmation_text` — one-use browser confirmation перед прямым нажатием;
- `style` — `primary`, `secondary`, `success` или `danger`;
- `read_only`, `idempotent`, `open_world` — точные MCP annotations для AI;
- `ai_description` — узкая инструкция, когда AI вправе выбрать эту операцию.

`confirmation_text` и AI policy — разные барьеры. Browser всегда получает
confirmation, если текст задан. В AI flow OpenCode спрашивает разрешение только
при policy `manual`; повторное browser-confirmation там отсутствует. Поэтому
мутационную операцию обычно настраивают как `manual` и дополнительно задают
понятный `confirmation_text` для ручной кнопки.

## AI-доступ к плагинам

Плагины закрыты для AI по умолчанию. Оператор на странице
**Настройки -> Плагины** задаёт три уровня:

1. **ИИ видит плагины** — глобальный выключатель всего plugin MCP surface.
2. **ИИ видит плагин** — публиковать конкретную страницу в `list_plugins` и
   разрешить `get_plugin_page`.
3. Для каждой операции:
   - `Запретить` (`deny`) — dedicated MCP tool не публикуется и runtime
     отклоняет stale-вызов;
   - `Разрешить` (`allow`) — OpenCode может вызвать tool без дополнительного
     подтверждения;
   - `Manual approve` (`manual`) — OpenCode спрашивает пользователя перед
     каждым вызовом.

Настройки хранятся server-side в `data/plugin-ai-policy.json`; это не secret и
не часть corporate wheel. Не редактируйте файл вручную — используйте UI или
`GET/PUT /api/v1/plugins/ai-policy`.

AI plugin surface работает только при `AUTODEPLOY_MCP_ENABLED=true`. Изменение
allow/manual добавляет permissions в новую OpenCode session, поэтому после
сохранения создайте новый чат. Ужесточение до `deny` действует fail-closed и для
старого чата на уровне MCP dispatch.

Когда плагины видимы, AutoDeploy MCP публикует:

- `list_plugins` — только разрешённые страницы;
- `get_plugin_page` — live fields/widgets и только незапрещённые operations;
- `calculate_plugin_state` — пересчёт conditions/widgets после изменения values;
- `search_plugin_reference_options` — ленивое разрешение `value_key` для
  `SELECT/MULTISELECT`, включая зависимые справочники;
- `validate_plugin_values` — authoritative Python validation перед операцией;
- отдельный stable tool для каждой operation с policy `allow` или `manual`.

Эти служебные read-only tools не передают полный каталог справочников в
начальный context: Copilot вызывает их только для выбранного плагина и нужного
поля. Для reference agent обязан использовать возвращённый `value_key`, а не
угадывать ID по label.

Не создавайте один универсальный `run_plugin(plugin_id, operation_id)`: отдельные
tools нужны, чтобы OpenCode применял точное permission rule к каждой операции.
Наличие `readOnlyHint=true` не превращает deny в allow и не заменяет политику.

## REST API

Основной contract (`environment` — обязательный выбранный key):

```text
GET  /api/v1/plugins
GET  /api/v1/plugins/{plugin_id}?environment=test_int
POST /api/v1/plugins/{plugin_id}/state
POST /api/v1/plugins/{plugin_id}/validate
POST /api/v1/plugins/{plugin_id}/fields/{field_path}/options
POST /api/v1/plugins/{plugin_id}/operations/{operation_id}
GET  /api/v1/plugins/ai-policy
PUT  /api/v1/plugins/ai-policy
```

`state`, `validate` и operation получают `plugin_version`. Stale version даёт
HTTP 409, неизвестный plugin/operation — 404, ошибка входных данных — 422.
Unexpected corporate exception остаётся 500 и записывается server logger; не
подменяйте её ложным успешным результатом.

## Тестовый шаблон

Плагин тестируется без React и без реальной сети. Минимальный private test:

```python
def test_capacity_plugin_contract(app_container):
    plugin = app_container.plugin_registry.get("reports.capacity")
    assert plugin.title

    page = app_container.plugins.describe("reports.capacity", "test_int")
    assert page["version"]
    assert {field["key"] for field in page["fields"]} == {"api", "include_plans"}

    validation = app_container.plugins.validate(
        plugin.plugin_id,
        "test_int",
        {"api": "known-id", "include_plans": True},
        page["version"],
    )
    assert validation.valid
```

Дополнительно проверяйте:

- registrar в чистом process и уникальность id;
- defaults и condition до первого клика;
- каждый SELECT/MULTISELECT: search, selected item pinning, invalid ID;
- block/plural field и dependent reference;
- validator с field-addressable error;
- render с пустым/частичным/полным состоянием и лимиты widgets;
- каждую operation: invalid state, success, exception, confirmation, values patch;
- service/environment routing без утечки auth;
- AI policy defaults `deny`, `allow`, `manual`, tools/list и stale deny;
- API 404/409/422 и browser smoke в светлой/тёмной теме.

## Чек-лист для AI-агента

Перед завершением нового корпоративного плагина агент обязан:

1. объяснить, почему это custom page, а не `BaseForm`;
2. создать модуль только под `src/corp_autodeploy/plugins/`;
3. переиспользовать `FieldDefinition` и corporate reference handlers;
4. получать интеграции только через `PluginContext.services`;
5. держать `render` read-only и вынести side effects в named operations;
6. задать точный `ai_description` и правдивые MCP annotations;
7. не включать AI visibility/policy автоматически — это выбор оператора;
8. не передавать browser/AI secrets, raw responses и confidential dictionary
   fields;
9. зарегистрировать plugin, добавить unit/contract tests и проверить restart;
10. обновить корпоративную документацию, если понадобился новый public contract.

Если для реализации приходится импортировать `webapp.plugin_runtime`, читать
`container` или добавлять private React-код, используемого public contract
недостаточно. Не обходите границу: сформулируйте обратно совместимое изменение
публичного ядра отдельной задачей.
