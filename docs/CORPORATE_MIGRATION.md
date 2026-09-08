# Миграция корпоративных форм в веб-версию

Практический пошаговый перенос первой формы из монолитного Tkinter-проекта
описан отдельно в [FIRST_CORPORATE_FORM_MIGRATION.md](FIRST_CORPORATE_FORM_MIGRATION.md).

## Целевая схема

Рекомендуется разделить поставку на два Python-пакета:

```text
public repository                      private corporate repository
gravitee-autodeploy                    corp-autodeploy
├── FastAPI и React                    ├── формы
├── BaseForm/FieldDefinition           ├── ITSM/TFS/Gravitee-сервисы
├── web runtime                        ├── обработчики справочников
├── launcher/updater                   └── регистрация расширения
└── безопасные заглушки интеграций
                 │                                  │
                 └──────── release pipeline ────────┘
                                      │
                         один offline release ZIP
```

React ничего не знает о корпоративной реализации. Он получает только безопасное
описание формы и результаты API. Формы, валидация, payload, авторизация и все
сетевые операции остаются в Python. Секреты не включаются ни в один wheel или
архив: установленный сервер читает их из пользовательского `config/.env`.

## Что переносится без переписывания

Форму не нужно конвертировать в JSON или React, если она уже наследуется от
`BaseForm` и использует стандартные `FieldDefinition`/`ReferenceConfig`.
Веб-runtime вызывает те же Python hooks:

```text
fields → validate → build_payload → pre_submit → HTTP submit
       → result hooks → polling
```

Без изменений поддерживаются стандартные типы полей, условия, `plural`, `BLOCK`,
зависимые справочники, `fetch_from_itsm()`, подтверждение операции и result/poll
hooks. В `pre_submit()` доступны совместимые
`self.screen.get_field_item()`/`get_field_items()` с полными объектами выбранных
элементов справочника.

Для кода, который раньше зависел от `FormScreen`, используйте два
UI-independent контракта:

```python
environment = self.current_environment
self.apply_form_data({"field_key": "value"})
```

`current_environment` заполняется и desktop-, и web-runtime. Применение данных
поддерживается в `ServerAction` и `fetch_from_itsm()`; в web-режиме накопленный
patch автоматически возвращается frontend. Старый прямой вызов
`self.screen.apply_form_data(...)` в этих двух hook также поддерживается для
плавной миграции. Доступ к `self.screen.app` намеренно не эмулируется.

Адаптация нужна, если форма:

- открывает Tkinter-диалоги или обращается к конкретным виджетам;
- реализует `CustomButton` с UI-логикой — такую операцию нужно оформить как
  `ServerAction`;
- использует собственный `FieldType`/Tkinter-виджет;
- хранит бизнес-правила только в обработчике события UI;
- ожидает label справочника там, где `ReferenceConfig.value_key` содержит ID;
- использует собственный экран результата вместо стандартных result hooks.

Старые `forms/base_form.py` и `forms/fields.py` нельзя копировать поверх новых
файлов целиком: корпоративные классы должны импортировать актуальные публичные
контракты.

## 1. Создание закрытого пакета

Минимальная структура отдельного корпоративного репозитория:

```text
corp-autodeploy/
├── pyproject.toml
├── src/corp_autodeploy/
│   ├── __init__.py
│   ├── registrar.py
│   ├── services.py
│   ├── references.py
│   └── forms/
│       ├── __init__.py
│       ├── create_api.py
│       └── ...
└── tests/
```

Пример `pyproject.toml`:

```toml
[build-system]
requires = ["setuptools>=75", "wheel"]
build-backend = "setuptools.build_meta"

[project]
name = "corp-autodeploy"
version = "1.0.0"
requires-python = ">=3.10,<3.14"
dependencies = ["gravitee-autodeploy>=1.0,<2"]

[tool.setuptools]
package-dir = {"" = "src"}

[tool.setuptools.packages.find]
where = ["src"]
```

Формы продолжают импортировать контракты из публичного ядра:

```python
from forms.base_form import BaseForm, ServerAction
from forms.fields import FieldDefinition, FieldType, ReferenceConfig
```

Ошибки кастомной валидации, относящиеся к конкретному полю, возвращайте через
публичный helper. Тогда web-интерфейс покажет сообщение непосредственно под
полем и переведёт к нему пользователя:

```python
def validate(self, form_data):
    errors = super().validate(form_data)
    if not form_data.get("context_path", "").startswith("/"):
        errors.append(self.validation_error(
            "context_path",
            "Context path должен начинаться с /",
        ))
    return errors
```

Старые строковые ошибки остаются совместимыми: ядро пытается определить поле
по его `key` или `label`. Для межполевых правил используйте явный helper, чтобы
не полагаться на текст сообщения.

## 2. Регистрация форм и AI-описаний

Публичное ядро вызывает один закрытый registrar при старте. Он регистрирует
формы, а для AI-маршрутизации добавляет назначение каждой новой формы:

```python
# corp_autodeploy/registrar.py
from config.form_routing import FORM_ROUTING, FormRoutingDescription
from corp_autodeploy.forms.create_api import CorporateCreateApiForm
from corp_autodeploy.forms.change_owner import ChangeOwnerForm


def register_forms(registry):
    forms = [CorporateCreateApiForm(), ChangeOwnerForm()]
    for form in forms:
        registry.register(form)

    FORM_ROUTING.update({
        "api.create": FormRoutingDescription(
            purpose="Создать новое API по корпоративному процессу.",
            use_when=("Требуется создать или зарегистрировать новое API.",),
            avoid_when=("Нужно изменить уже существующее API.",),
        ),
        "api.change_owner": FormRoutingDescription(
            purpose="Изменить владельца существующего API.",
            use_when=("Требуется передать API другой команде или владельцу.",),
            avoid_when=("Создаётся новое API.",),
        ),
    })
```

Регистрация формы с существующим `form_id` намеренно заменяет публичную форму-
заглушку. Для каждой зарегистрированной формы обязательно должно существовать
ровно одно routing-описание, иначе AI-каталог отклонит конфигурацию.

Этот каталог не отправляется в основную Copilot-сессию при старте. Он строится
только при первом семантическом поиске формы, один раз сохраняется в отдельной
tool-free сессии `form-search` с thinking=`none` и затем переиспользуется до
закрытия чата. Поэтому routing-описание должно раскрывать назначение и границы
формы, но не должно содержать секреты, реальные заявки или значения
справочников. Сами ``form.fields`` и схема формы в эту поисковую сессию не
передаются. Схема запрашивается только после выбора одной формы.

Лучше сохранить стандартные категории `api`, `apps`, `other`. Если нужны новые,
registrar должен также зарегистрировать их в `CATEGORIES` и `CATEGORY_ORDER`,
иначе формы будут доступны по API, но не появятся в каталоге интерфейса.

## 3. Корпоративные сервисы

Сервисам необязательно наследоваться от публичных заглушек. Фабрика возвращает
объекты, реализующие методы, которые вызывают формы и AI-контекст:

```python
# corp_autodeploy/services.py
from webapp.extensions import RuntimeServices


class CorporateITSM:
    def __init__(self, env, http):
        self.env = env
        self.http = http

    def get_ticket(self, ticket_id: str, environment: str = ""):
        # URL и auth берутся из env.get(...); вернуть Python dict/list.
        ...


class CorporateTFS:
    def __init__(self, env, http):
        self.env = env
        self.http = http

    def get_pull_request(self, reference, environment: str = ""):
        ...


class CorporateGravitee:
    def __init__(self, env, http):
        self.env = env
        self.http = http
        # Здесь размещаются методы, используемые корпоративными формами.


def create_services(env_manager, http_client):
    return RuntimeServices(
        itsm=CorporateITSM(env_manager, http_client),
        tfs=CorporateTFS(env_manager, http_client),
        gravitee=CorporateGravitee(env_manager, http_client),
    )
```

Эти объекты автоматически попадут в `form.itsm_service`, `form.tfs_service` и
`form.gravitee_service`. Не следует хранить токены в атрибутах классов,
исходниках, логах или возвращаемых frontend-моделях — читать их нужно через
переданный `EnvManager` только на сервере.

## 4. Корпоративные справочники

Для удалённых справочников рекомендуется собственный handler, а не изменение
публичного `_URL_MAP`:

```python
# corp_autodeploy/references.py
from handlers.base_reference_handler import BaseReferenceHandler


class CorporateReferenceHandler(BaseReferenceHandler):
    def __init__(self, env, http, cache):
        self.env = env
        self.http = http
        self.cache = cache

    def supports(self, config):
        return config.source == "corp_http"

    def load(self, config, environment="", extra_params=None):
        # Вернуть list[dict]. Каждый item обязан содержать
        # config.value_key и config.label_key.
        ...


def create_handlers(env_manager, http_client, cache):
    return [CorporateReferenceHandler(env_manager, http_client, cache)]
```

В форме:

```python
ReferenceConfig(
    source="corp_http",
    resource="gravitee_apis",
    value_key="id",
    label_key="name",
    search_keys=("context_path", "name", "id"),
)
```

`search_keys` определяет поиск, `value_key` — сохраняемое значение, а
`label_key` — подпись. Для `MULTISELECT` используется тот же контракт. Уже
существующие публичные справочники можно оставить в `config/references`.
Закрытые JSON-файлы лучше хранить внутри `corp_autodeploy`, включить в его wheel
как package data и читать отдельным handler с `source="corp_local"`: встроенный
`source="local"` ищет файлы только в публичном `config/references`.

Глобальная страница поиска API и приложений не должна знать корпоративные
ресурсы. Добавьте в тот же закрытый пакет отдельную фабрику каталогов:

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

Фабрика обязана вернуть обе записи (`api` и `application`). Их `source` и
`resource` обслуживает обычный `AUTODEPLOY_REFERENCE_HANDLER_FACTORY`, поэтому
загрузка, авторизация и кеш остаются только в корпоративном handler. Публичный
`FormRuntime` выполняет лишь поиск по объявленным `search_keys`.

## 5. Подключение расширения

После установки обоих wheel в `.env` задаются только import paths:

```env
AUTODEPLOY_FORM_REGISTRAR=corp_autodeploy.registrar:register_forms
AUTODEPLOY_SERVICE_PROVIDER=corp_autodeploy.services:create_services
AUTODEPLOY_REFERENCE_HANDLER_FACTORY=corp_autodeploy.references:create_handlers
AUTODEPLOY_SEARCH_CATALOG_FACTORY=corp_autodeploy.search_catalogs:create_search_catalogs
AUTODEPLOY_ENVIRONMENT_HOOK=corp_autodeploy.environment:create_environment_hook
```

Если при смене контура нужна отдельная корпоративная подготовка, её контракт и
пошаговое подключение описаны в
[CORPORATE_ENVIRONMENT_HOOK.md](CORPORATE_ENVIRONMENT_HOOK.md).

Для локальной проверки разработчика:

```powershell
cd gravitee-autodeploy
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[test]"
.\.venv\Scripts\python.exe -m pip install -e ..\corp-autodeploy
.\.venv\Scripts\python.exe -m webapp
```

## 6. Сборка единого корпоративного релиза

Закрытый pipeline должен:

1. получить зафиксированную версию публичного ядра;
2. собрать и протестировать `corp-autodeploy`;
3. собрать frontend публичного ядра;
4. передать закрытый wheel в release builder;
5. smoke-test установить итоговый ZIP;
6. сначала опубликовать immutable app archive и только затем атомарно заменить
   TFS manifest.

Пример сборки:

```powershell
python -m build --wheel ..\corp-autodeploy

python scripts/build_release.py `
  --artifact-url "https://tfs.example/releases/gravitee-autodeploy-1.4.0.zip" `
  --extra-wheel "..\corp-autodeploy\dist\corp_autodeploy-1.4.0-py3-none-any.whl" `
  --wheel-platform win_amd64 `
  --python-version 310 --python-version 311 `
  --python-version 312 --python-version 313

python scripts/verify_release.py `
  build/release/gravitee-autodeploy-app-1.4.0.zip
```

Если закрытый пакет имеет дополнительные зависимости, wheel каждой зависимости
также нужно передать повторяемым `--extra-wheel` (либо расширить корпоративный
build script, чтобы он наполнял `wheelhouse`). Установка на компьютере
пользователя всегда выполняется с `--no-index`, без обращения к PyPI/npm.

## 7. Проверка миграции

Перед rollout необходимо проверить:

- `/api/v1/health` показывает ожидаемое количество форм;
- все формы присутствуют в `/api/v1/forms` и в визуальном каталоге;
- каждая форма успешно отдаётся через `/api/v1/forms/{form_id}`;
- условия видимости корректно пересчитываются через `/state`;
- SELECT/MULTISELECT и зависимые справочники возвращают правильные ID;
- `/preview` строит тот же payload, что старая Tkinter-форма;
- submit вызывает ожидаемый endpoint, auth, headers и `pre_submit()`;
- polling и финальный статус совпадают со старым клиентом;
- AI выбирает каждую новую форму по её routing-описанию;
- в frontend/API/log-файлы не попадают секреты и сырые конфиденциальные ответы.

Для миграции безопаснее сначала оставить Tkinter-клиент доступным, сравнить
payload старой и веб-формы на тестовом окружении, затем включить веб-версию для
пилотной группы. Launcher хранит предыдущую установленную версию и позволяет
выполнить rollback без изменения пользовательского `.env`.
