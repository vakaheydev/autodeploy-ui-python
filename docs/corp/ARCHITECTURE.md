# Архитектура корпоративного пакета

## Целевая структура

Private repository должен быть обычным installable Python package:

```text
corp-autodeploy/
├── AGENTS.md
├── pyproject.toml
├── src/
│   └── corp_autodeploy/
│       ├── __init__.py
│       ├── registrar.py
│       ├── services.py
│       ├── references.py
│       ├── search_catalogs.py
│       ├── environment.py
│       ├── plugins/
│       │   ├── __init__.py
│       │   ├── registrar.py
│       │   └── capacity_report.py
│       ├── forms/
│       │   ├── __init__.py
│       │   └── create_api.py
│       └── reference_data/             # private package data, без секретов
├── tests/
└── docs/
```

Использование `src/` layout обязательно: оно не даёт тестам случайно импортировать
файлы из checkout вместо установленного wheel. Все корпоративные импорты должны
начинаться с `corp_autodeploy`.

Минимальный `pyproject.toml`:

```toml
[build-system]
requires = ["setuptools>=75", "wheel"]
build-backend = "setuptools.build_meta"

[project]
name = "corp-autodeploy"
version = "1.0.0"
requires-python = ">=3.10,<3.14"
dependencies = [
  "gravitee-autodeploy==<версия-публичного-ядра>",
  "requests==2.32.3", # только если private adapters действительно используют её
]

[tool.setuptools]
package-dir = {"" = "src"}

[tool.setuptools.packages.find]
where = ["src"]

[tool.setuptools.package-data]
corp_autodeploy = ["reference_data/*.json"]
```

Корпоративная зависимость не добавляется в public `requirements.txt`. В offline
release вместе с private wheel должны войти wheel всех его зависимостей.

## Модель композиции

На старте Python server:

1. создаёт public container и безопасные default services;
2. импортирует private factories по значениям `.env`;
3. регистрирует public forms, затем private forms;
4. регистрирует private custom page плагины в отдельном registry;
5. ставит private reference handlers перед встроенными fallback handlers;
6. загружает ровно два global search catalog;
7. создаёт environment hook;
8. публикует один REST API, React SPA и optional MCP на localhost.

Private форма с тем же `form_id` заменяет public форму. Frontend не знает, какой
package создал JSON schema.

## Extension points

Все import paths имеют формат `package.module:callable`.

| `.env` key | Точная сигнатура | Жизненный цикл |
|---|---|---|
| `AUTODEPLOY_FORM_REGISTRAR` | `register_forms(registry) -> None` | один раз при startup |
| `AUTODEPLOY_PLUGIN_REGISTRAR` | `register_plugins(registry) -> None` | один раз при startup |
| `AUTODEPLOY_SERVICE_PROVIDER` | `create_services(env_manager, http_client) -> RuntimeServices` | factory загружается при startup, services создаются runtime для запросов |
| `AUTODEPLOY_REFERENCE_HANDLER_FACTORY` | `create_handlers(env_manager, http_client, cache) -> Iterable[handler]` | один раз при startup |
| `AUTODEPLOY_SEARCH_CATALOG_FACTORY` | `create_search_catalogs(env_manager) -> Mapping[str, ReferenceConfig]` | один раз при startup |
| `AUTODEPLOY_ENVIRONMENT_HOOK` | `create_environment_hook(env_manager) -> hook(previous, current)` | factory один раз, hook при реальной смене environment |
| `AUTODEPLOY_UPDATE_PROVIDER` | `create_provider(paths, values) -> provider` | отдельный launcher process; callable должен быть доступен его Python, не только app `.venv` |

Основные типы импортируются из public wheel:

```python
from forms.base_form import BaseForm, ServerAction
from forms.fields import FieldDefinition, FieldType, ReferenceConfig
from handlers.base_reference_handler import BaseReferenceHandler
from plugins import PluginDefinition, PluginOperation, PluginRegistry
from webapp.extensions import (
    EnvironmentChangeRejected,
    RuntimeServices,
)
```

Не наследуйте private service от public placeholder, если это не даёт пользы:
достаточно реализовать вызываемые методы. Не копируйте `BaseForm`, `FieldType`,
registry или runtime в private package.

## Registrar

Registrar является единственной точкой состава форм и их AI routing:

```python
from config.form_routing import FORM_ROUTING, FormRoutingDescription
from corp_autodeploy.forms.create_api import CreateApiForm


def register_forms(registry) -> None:
    form = CreateApiForm()
    registry.register(form)
    FORM_ROUTING[form.form_id] = FormRoutingDescription(
        purpose="Создать API по корпоративному процессу.",
        use_when=("Пользователь просит создать или зарегистрировать новое API.",),
        avoid_when=("Меняется только существующий ingress или владелец.",),
    )
```

Для каждой зарегистрированной формы routing entry обязателен. Лишний entry для
незарегистрированного `form_id` также считается ошибкой. Описание должно
различать соседние операции, но не повторять поля формы.

Плагины регистрируются отдельно и не получают `FormRoutingDescription`:

```python
from corp_autodeploy.plugins.capacity_report import CAPACITY_REPORT


def register_plugins(registry) -> None:
    registry.register(CAPACITY_REPORT)
```

Полный plugin contract, виджеты и отдельная AI policy описаны в
[PLUGINS.md](PLUGINS.md).

Если добавляется новая категория, registrar обновляет оба public registry:

```python
from config.categories import CATEGORIES, CATEGORY_ORDER

CATEGORIES["security"] = "Безопасность"
if "security" not in CATEGORY_ORDER:
    CATEGORY_ORDER.append("security")
```

## Public/private ownership

| Отвечает public core | Отвечает private package |
|---|---|
| HTTP API и validation pipeline | Конкретные формы и domain rules |
| Generic React renderer | Корпоративные подписи/описания полей |
| Plugin REST/MCP runtime и generic widgets | Custom page definitions и operation handlers |
| Secrets whitelist и write-only transport | Значения secrets в пользовательском `.env` |
| Reference paging/search engine | URL, auth и преобразование private dictionaries |
| Submit/auth framework | Endpoint, auth type, payload и pre-submit logic формы |
| AI orchestration и draft storage | Routing descriptions и private source adapters |
| Release/rollback engine | TFS manifest location, private wheels и optional launcher adapter |

## Версионирование контракта

Private package должен фиксировать совместимую версию public core, а pipeline —
тестировать именно эту пару. Перед обновлением core:

1. установить новый public wheel вместе с private package в чистое окружение;
2. запустить contract/integration suite;
3. проверить все формы через catalog, state, validate и preview;
4. собрать и smoke-test итоговый offline archive;
5. только после этого изменить pinned version private package.

Импорт private API (`_name`) или чтение внутреннего состояния container считается
ошибкой архитектуры, даже если текущая версия это допускает.
