# Пошаговая миграция первой корпоративной формы

Эта инструкция описывает перенос одной корпоративной формы
`forms/create_api_form.py` из старого монолитного Tkinter-проекта в отдельный
закрытый Python-пакет, подключаемый к публичному ядру Gravitee AutoDeploy.

Старый Tkinter-проект на первом этапе не изменяется. Внутри
`corp-autodeploy` создаётся изолированный пакет расширения, в который
переносятся только форма создания API и её непосредственные зависимости.

Исходная структура:

```text
workspace/
├── corp-autodeploy/           # старый Tkinter-проект целиком
│   ├── forms/
│   │   └── create_api_form.py
│   ├── services/
│   ├── config/
│   ├── ui/
│   └── ...
│
└── gravitee-autodeploy/       # новое публичное ядро
    ├── forms/
    ├── webapp/
    ├── frontend/
    └── ...
```

## Шаг 1. Создать миграционный пакет

Пока старый проект ещё используется, создайте пакет в отдельной подпапке:

```text
corp-autodeploy/
├── forms/                     # старый код, пока не трогаем
├── services/
├── ui/
├── ...
│
└── extension/
    ├── pyproject.toml
    ├── src/
    │   └── corp_autodeploy/
    │       ├── __init__.py
    │       ├── registrar.py
    │       ├── services.py
    │       ├── references.py
    │       ├── integrations/
    │       │   ├── __init__.py
    │       │   ├── itsm.py
    │       │   ├── tfs.py
    │       │   └── gravitee.py
    │       ├── forms/
    │       │   ├── __init__.py
    │       │   └── create_api_form.py
    │       └── reference_data/
    └── tests/
```

Так старый Tkinter остаётся работоспособным, а новая реализация развивается
отдельно. Когда миграция закончится, содержимое `extension/` можно будет
перенести в корень закрытого репозитория.

## Шаг 2. Создать `pyproject.toml`

Файл `corp-autodeploy/extension/pyproject.toml`:

```toml
[build-system]
requires = ["setuptools>=75", "wheel"]
build-backend = "setuptools.build_meta"

[project]
name = "corp-autodeploy"
version = "0.1.0"
requires-python = ">=3.10,<3.14"
dependencies = [
    "gravitee-autodeploy==1.0.0"
]

[tool.setuptools]
package-dir = {"" = "src"}

[tool.setuptools.packages.find]
where = ["src"]

[tool.setuptools.package-data]
corp_autodeploy = [
    "reference_data/*.json"
]
```

Создайте пустые файлы:

```text
extension/src/corp_autodeploy/__init__.py
extension/src/corp_autodeploy/forms/__init__.py
extension/src/corp_autodeploy/integrations/__init__.py
```

## Шаг 3. Подготовить общее виртуальное окружение

Выполняйте команды из нового публичного ядра:

```powershell
cd gravitee-autodeploy

py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[test]"
.\.venv\Scripts\python.exe -m pip install -e ..\corp-autodeploy\extension --no-deps
```

`--no-deps` здесь нужен, чтобы `pip` не пытался искать
`gravitee-autodeploy` в PyPI: публичное ядро уже установлено editable-пакетом.

Проверка:

```powershell
.\.venv\Scripts\python.exe -c "import corp_autodeploy; print(corp_autodeploy.__file__)"
```

Должен отобразиться путь внутри:

```text
corp-autodeploy\extension\src\corp_autodeploy
```

## Шаг 4. Скопировать первую форму

Скопируйте:

```text
corp-autodeploy/forms/create_api_form.py
```

в:

```text
corp-autodeploy/extension/src/corp_autodeploy/forms/create_api_form.py
```

Старый файл пока не удаляйте.

## Шаг 5. Исправить импорты формы

Контракты формы должны импортироваться из публичного ядра:

```python
from forms.base_form import BaseForm, ServerAction
from forms.fields import FieldDefinition, FieldType, ReferenceConfig
```

Это правильные импорты. Не копируйте в закрытый пакет старые:

```text
forms/base_form.py
forms/fields.py
forms/registry.py
forms/loader.py
```

Корпоративные модули должны импортироваться через закрытый namespace:

```python
from corp_autodeploy.integrations.itsm import CorporateITSM
from corp_autodeploy.some_module import some_function
```

Нельзя оставлять импорты вроде:

```python
from services.corporate_itsm import CorporateITSM
from config.corporate_urls import URLS
```

Пакеты `services` и `config` уже существуют в публичном ядре, поэтому возникнет
конфликт имён. Замените их на:

```python
from corp_autodeploy.integrations.itsm import CorporateITSM
from corp_autodeploy.config import URLS
```

Но лучше, чтобы форма вообще не создавала сервисы самостоятельно, а
пользовалась:

```python
self.itsm_service
self.tfs_service
self.gravitee_service
```

## Шаг 6. Провести аудит зависимостей формы

В старом корпоративном проекте выполните:

```powershell
rg -n "^from |^import |self\.(itsm_service|tfs_service|gravitee_service)|self\.screen|tkinter|messagebox|filedialog|CustomButton" forms/create_api_form.py
```

Разделите найденное на четыре группы.

### 1. Публичные контракты

```python
forms.base_form
forms.fields
forms.result_config
config.environments
```

Их не переносим.

### 2. Корпоративные сервисы

```text
ITSM
TFS
Gravitee
корпоративные HTTP endpoint
```

Переносим в `corp_autodeploy/integrations/`.

### 3. Корпоративные справочники

```text
JSON-файлы
URL maps
response processors
```

Переносим в `reference_data/` и `references.py`.

### 4. Tkinter

```python
messagebox
askstring
filedialog
tk.Variable
widget.get()
self.screen.some_widget
```

Такой код придётся адаптировать.

## Шаг 7. Сначала добиться регистрации формы

Создайте `corp_autodeploy/registrar.py`:

```python
from config.form_routing import FORM_ROUTING, FormRoutingDescription
from corp_autodeploy.forms.create_api_form import CreateApiForm


def register_forms(registry):
    registry.register(CreateApiForm())

    FORM_ROUTING["api.create"] = FormRoutingDescription(
        purpose="Создать и зарегистрировать новое API по корпоративному процессу.",
        use_when=(
            "Пользователь просит создать новое API.",
            "Нужно зарегистрировать API в Gravitee.",
            "Указаны имя, context path, владелец или параметры endpoint.",
        ),
        avoid_when=(
            "Нужно изменить уже существующее API.",
            "Нужно только включить или выключить ingress.",
            "Нужно создать подписку приложения на API.",
        ),
    )
```

Если фактический `form_id` другой, используйте его вместо `api.create`.

Важно сохранить старый `form_id`:

```python
@property
def form_id(self) -> str:
    return "api.create"
```

Корпоративная форма с таким ID заменит публичную форму-заглушку.

## Шаг 8. Подключить registrar в `.env`

Для запуска из исходников создайте `gravitee-autodeploy/.env` на основе
`.env.example` и добавьте:

```dotenv
AUTODEPLOY_FORM_REGISTRAR=corp_autodeploy.registrar:register_forms
AUTODEPLOY_SERVICE_PROVIDER=
AUTODEPLOY_REFERENCE_HANDLER_FACTORY=
AUTODEPLOY_SEARCH_CATALOG_FACTORY=
AUTODEPLOY_ENVIRONMENT_HOOK=
```

На этом этапе специально оставляем сервисы и справочники пустыми. Сначала нужно
проверить сам импорт формы.

Запустите:

```powershell
cd gravitee-autodeploy
.\.venv\Scripts\python.exe -m webapp
```

Проверьте:

```text
http://127.0.0.1:8765/api/v1/forms
```

Форма `api.create` должна присутствовать. Затем проверьте:

```text
http://127.0.0.1:8765/api/v1/forms/api.create?environment=test_int
```

Если здесь возникает исключение, проблема находится непосредственно в:

- импортах формы;
- вычислении `fields`;
- `title`, `category` или `form_id`;
- вызове корпоративного кода во время создания формы.

## Шаг 9. Убрать выполнение работы при импорте

В форме нельзя выполнять при импорте:

```python
ticket = itsm.get_ticket(...)
apis = gravitee.get_apis(...)
token = load_token(...)
requests.get(...)
```

Также не следует загружать справочники прямо внутри свойства `fields`.
Допустимо только декларативное описание:

```python
@property
def fields(self):
    return [
        FieldDefinition(...),
        FieldDefinition(...),
    ]
```

Сеть должна вызываться только через:

- reference handler;
- `fetch_from_itsm()`;
- `pre_submit()`;
- серверный action;
- submit/poll hooks.

## Шаг 10. Подключить корпоративные сервисы

Создайте `corp_autodeploy/services.py`:

```python
from webapp.extensions import RuntimeServices
from corp_autodeploy.integrations.itsm import CorporateITSM
from corp_autodeploy.integrations.tfs import CorporateTFS
from corp_autodeploy.integrations.gravitee import CorporateGravitee


def create_services(env_manager, http_client):
    return RuntimeServices(
        itsm=CorporateITSM(env_manager, http_client),
        tfs=CorporateTFS(env_manager, http_client),
        gravitee=CorporateGravitee(env_manager, http_client),
    )
```

Минимальный ITSM-сервис:

```python
# corp_autodeploy/integrations/itsm.py

class CorporateITSM:
    def __init__(self, env_manager, http_client):
        self.env = env_manager
        self.http = http_client

    def get_ticket(self, ticket_id: str, environment: str = ""):
        login = self.env.get("ITSM_LOGIN")
        password = self.env.get("ITSM_PASSWORD")

        # Здесь переносится существующий корпоративный запрос.
        ...
```

TFS:

```python
# corp_autodeploy/integrations/tfs.py

class CorporateTFS:
    def __init__(self, env_manager, http_client):
        self.env = env_manager
        self.http = http_client

    def get_pull_request(self, reference, environment: str = ""):
        token = self.env.get("TFS_TOKEN")
        ...
```

Gravitee:

```python
# corp_autodeploy/integrations/gravitee.py

class CorporateGravitee:
    def __init__(self, env_manager, http_client):
        self.env = env_manager
        self.http = http_client

    def get_apis(self, environment: str):
        ...

    def create_api_endpoint(self, environment: str) -> str:
        ...
```

Сохраняйте названия методов, которые уже вызывает `CreateApiForm`. Тогда внутри
формы потребуется минимум изменений.

Подключите factory:

```dotenv
AUTODEPLOY_SERVICE_PROVIDER=corp_autodeploy.services:create_services
```

После изменения `.env` полностью перезапустите сервер.

## Шаг 11. Перенести `fetch_from_itsm()`

Существующий метод можно сохранить:

```python
@property
def itsm_support(self) -> bool:
    return True


def fetch_from_itsm(self, environment: str, ticket_id: str):
    ticket = self.itsm_service.get_ticket(ticket_id, environment)

    return {
        "name": ticket.get("api_name"),
        "description": ticket.get("description"),
        "context_path": ticket.get("context_path"),
    }
```

Ключи результата должны совпадать с `field.key`.

Не возвращайте браузеру:

- токены;
- authentication headers;
- сырой объект заявки целиком;
- служебные ITSM-поля;
- персональные данные, не используемые формой.

После подключения проверьте `POST /api/v1/forms/api.create/ticket` с телом:

```json
{
  "environment": "test_int",
  "ticket_id": "REQ-123456"
}
```

## Шаг 12. Разобрать справочники формы

Посмотрите каждый `ReferenceConfig` в `CreateApiForm`.

Например:

```python
ReferenceConfig(
    source="local",
    resource="api_categories.json",
    value_key="id",
    label_key="name",
)
```

Если `api_categories.json` корпоративный, нельзя оставлять `source="local"`.
Публичный handler будет искать его в публичном ядре. Замените источник:

```python
ReferenceConfig(
    source="corp_local",
    resource="api_categories.json",
    value_key="id",
    label_key="name",
)
```

И положите файл сюда:

```text
corp_autodeploy/reference_data/api_categories.json
```

Для удалённого справочника:

```python
ReferenceConfig(
    source="corp_http",
    resource="gravitee_apis",
    value_key="id",
    label_key="name",
    search_keys=("context_path", "name", "id"),
)
```

## Шаг 13. Реализовать handler справочников

Минимальный локальный handler:

```python
# corp_autodeploy/references.py

import json
from importlib.resources import files

from handlers.base_reference_handler import BaseReferenceHandler


class CorporateReferenceHandler(BaseReferenceHandler):
    def __init__(self, env_manager, http_client, cache):
        self.env = env_manager
        self.http = http_client
        self.cache = cache

    def supports(self, config):
        return config.source in {"corp_local", "corp_http"}

    def load(self, config, environment="", extra_params=None):
        if config.source == "corp_local":
            return self._load_local(config)

        return self._load_http(
            config,
            environment,
            extra_params or {},
        )

    def _load_local(self, config):
        resource = files("corp_autodeploy.reference_data").joinpath(
            config.resource
        )

        data = json.loads(resource.read_text(encoding="utf-8"))
        items = data if isinstance(data, list) else data.get("items", [])

        return [
            item
            for item in items
            if isinstance(item, dict)
            and config.value_key in item
            and config.label_key in item
        ]

    def _load_http(self, config, environment, params):
        if config.resource == "gravitee_apis":
            # Лучше делегировать конкретному корпоративному клиенту
            # либо реализовать вызов здесь.
            ...

        return []


def create_handlers(env_manager, http_client, cache):
    return [
        CorporateReferenceHandler(
            env_manager,
            http_client,
            cache,
        )
    ]
```

Добавьте файл:

```text
corp_autodeploy/reference_data/__init__.py
```

И подключите factory:

```dotenv
AUTODEPLOY_REFERENCE_HANDLER_FACTORY=corp_autodeploy.references:create_handlers
```

Для глобального поиска API и приложений добавьте:

```python
# corp_autodeploy/search_catalogs.py
from forms.fields import ReferenceConfig


def create_search_catalogs(env_manager):
    return {
        "api": ReferenceConfig(
            source="corp_http",
            resource="gravitee_apis",
            value_key="id",
            label_key="name",
            search_keys=("context_path", "name", "id"),
        ),
        "application": ReferenceConfig(
            source="corp_http",
            resource="gravitee_applications",
            value_key="id",
            label_key="name",
            search_keys=("azp", "name", "id"),
        ),
    }
```

И подключите её:

```dotenv
AUTODEPLOY_SEARCH_CATALOG_FACTORY=corp_autodeploy.search_catalogs:create_search_catalogs
```

Это только декларация каталогов. Реальные HTTP-вызовы продолжает выполнять
`CorporateReferenceHandler`, зарегистрированный предыдущей настройкой.

После перезапуска проверьте options endpoint соответствующего поля:

```text
POST /api/v1/forms/api.create/fields/category/options
```

Пример тела:

```json
{
  "environment": "test_int",
  "values": {},
  "query": "",
  "offset": 0,
  "limit": 100,
  "refresh": false
}
```

## Шаг 14. Проверить типы справочников

Для каждого `SELECT`:

```python
field_type=FieldType.SELECT
```

значением формы будет один `value_key`:

```json
{
  "owner": "owner-id"
}
```

Для каждого `MULTISELECT`:

```python
field_type=FieldType.MULTISELECT
```

значением будет массив:

```json
{
  "categories": ["category-1", "category-2"]
}
```

Убедитесь, что старый `build_payload()` ожидает именно ID, а не отображаемый
`label`.

Если `pre_submit()` нужен полный объект:

```python
def pre_submit(self, form_data, payload, environment):
    owner = self.screen.get_field_item("owner")
    categories = self.screen.get_field_items("categories")
```

Это поддерживается серверным runtime.

## Шаг 15. Убрать Tkinter из первой формы

Если форма содержит:

```python
messagebox.showwarning(...)
askstring(...)
filedialog.askopenfilename(...)
self.screen.apply_form_data(...)
```

`self.screen.app.current_environment.get()` замените на независимую от UI
строку `self.current_environment`.

Старый `CustomButton` всё равно нужно заменить на `ServerAction`, но внутри его
server handler можно временно оставить `self.screen.apply_form_data(...)` или
использовать предпочтительный фасад `self.apply_form_data(...)`. Web-runtime
превратит такой вызов в patch для браузера. Затем перенесите бизнес-логику в
отдельный метод:

```python
def calculate_api_values(self, environment, form_data):
    return {
        "name": "...",
        "context_path": "...",
    }
```

Для веба добавьте `ServerAction`:

```python
from forms.base_form import ServerAction


def get_server_actions(self):
    return [
        ServerAction(
            action_id="calculate-api",
            label="Рассчитать параметры API",
            handler=self._calculate_api_action,
            style="Primary",
        )
    ]


def _calculate_api_action(self, environment, form_data):
    values = self.calculate_api_values(environment, form_data)
    self.apply_form_data(values)  # совместимо с desktop и web
    return {"message": "Параметры рассчитаны"}
```

Явный `return {"values": values}` также поддерживается и предпочтителен для
нового server-only кода. Если используются оба варианта, явно возвращённые
значения имеют приоритет.

Старый `CustomButton` можно пока оставить в старой копии формы.

## Шаг 16. Проверить состояние формы

Откройте форму в браузере и проверьте:

- все поля появились;
- значения по умолчанию работают;
- условные поля появляются и исчезают;
- `SELECT` возвращает одно значение;
- `MULTISELECT` возвращает несколько;
- зависимые справочники получают родительские значения;
- поиск работает по `search_keys`;
- нет недоступных legacy-кнопок.

Если форма отображается, но возле кнопки написано, что Tkinter callback
недоступен, значит в ней остался `CustomButton`, для которого ещё не создан
`ServerAction`.

## Шаг 17. Сравнить preview со старой формой

Возьмите один безопасный тестовый пример:

```json
{
  "name": "Test.API",
  "description": "Тестовое API",
  "context_path": "/test/api",
  "owner": "owner-id",
  "categories": ["test"]
}
```

В старой версии сохраните результат:

```python
old_form.build_payload(values)
```

В новой версии вызовите `POST /api/v1/forms/api.create/preview`:

```json
{
  "environment": "test_int",
  "values": {
    "name": "Test.API",
    "description": "Тестовое API",
    "context_path": "/test/api",
    "owner": "owner-id",
    "categories": ["test"]
  },
  "form_version": "<версия из GET /forms/api.create>"
}
```

Сравните:

- JSON payload;
- endpoint;
- HTTP method;
- auth type;
- заголовки;
- изменения из `pre_submit()`.

Они должны совпасть с Tkinter-версией.

## Шаг 18. Только после этого проверять submit

Сначала проверьте:

- тестовое окружение;
- тестовый API;
- отсутствие production-токена;
- корректный preview;
- наличие подтверждения.

Если операция требует подтверждения:

```python
def confirm_submit(self) -> bool:
    return True
```

Web runtime сначала вернёт confirmation token и только после явного
подтверждения выполнит запрос.

## Шаг 19. Добавить минимальные тесты

Файл `extension/tests/test_registration.py`:

```python
from forms.loader import register_all_forms
from forms.registry import FormRegistry

from corp_autodeploy.registrar import register_forms


def test_create_api_form_registered():
    registry = FormRegistry()
    registry.clear()

    register_all_forms()
    register_forms(registry)

    form = registry.get("api.create")

    assert form.form_id == "api.create"
    assert form.__class__.__module__.startswith("corp_autodeploy.")
```

Файл `extension/tests/test_create_api.py`:

```python
from corp_autodeploy.forms.create_api_form import CreateApiForm


def test_create_api_payload():
    form = CreateApiForm()

    payload = form.build_payload({
        "name": "Test.API",
        "description": "Test",
        "context_path": "/test/api",
        "owner": "owner-id",
        "categories": ["test"],
    })

    assert payload["name"] == "Test.API"
    assert payload["contextPath"] == "/test/api"
```

Запуск:

```powershell
cd gravitee-autodeploy
.\.venv\Scripts\python.exe -m pytest ..\corp-autodeploy\extension\tests -v
```

## Контрольные точки

Не переходите к следующей, пока предыдущая не работает:

1. `corp_autodeploy` импортируется.
2. Registrar загружается.
3. `api.create` присутствует в `/api/v1/forms`.
4. Документ формы возвращается без ошибки.
5. Форма открывается в React.
6. Локальные справочники загружаются.
7. HTTP-справочники загружаются.
8. `fetch_from_itsm()` работает.
9. Python validation работает.
10. Preview совпадает со старым payload.
11. Тестовый submit работает.
12. Polling и результат работают.

После этого форма `create_api_form.py` считается полностью мигрированной. Затем
можно переносить следующую форму, повторно используя уже созданные сервисы и
reference handlers.
