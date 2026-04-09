# Руководство разработчика — Gravitee Admin UI

## Содержание

- [1. Архитектура приложения: модули](#1-архитектура-приложения-модули)
  - [Структура навигации](#структура-навигации)
  - [Добавить новый модуль на главный экран](#добавить-новый-модуль-на-главный-экран)
- [2. Модуль поиска](#2-модуль-поиска)
  - [Как работает поиск](#как-работает-поиск)
  - [Добавить новый раздел поиска](#добавить-новый-раздел-поиска)
  - [Изменить поля поиска у существующего раздела](#изменить-поля-поиска-у-существующего-раздела)
  - [Настроить поля в детальной карточке](#настроить-поля-в-детальной-карточке)
- [3. Добавить новую форму / изменить существующую](#3-добавить-новую-форму--изменить-существующую)
  - [Создать новую форму](#создать-новую-форму)
  - [Добавить новую категорию](#добавить-новую-категорию)
  - [Типы полей](#типы-полей)
  - [Условное поле](#условное-поле-показатьскрыть-при-выборе-другого)
  - [Изменить существующую форму](#изменить-существующую-форму)
- [4. Изменить обработку сабмита и конструирование JSON](#4-изменить-обработку-сабмита-и-конструирование-json)
  - [Как работает сабмит](#как-работает-сабмит)
  - [Изменить URL (куда летит запрос)](#изменить-url-куда-летит-запрос)
  - [Изменить структуру JSON](#изменить-структуру-json-payload)
  - [Изменить HTTP метод](#изменить-http-метод)
  - [Добавить заголовки к запросу](#добавить-дополнительные-заголовки-к-запросу)
- [5. Экран результата после сабмита](#5-экран-результата-после-сабмита)
  - [Как работает экран результата](#как-работает-экран-результата)
  - [Настроить заголовок и автообновление](#настроить-заголовок-и-автообновление)
  - [Кастомный контент результата](#кастомный-контент-результата)
  - [Включить автоопрос (polling)](#включить-автоопрос-polling)
- [6. UI-утилиты: диалоги](#6-ui-утилиты-диалоги)
  - [Информационные диалоги](#информационные-диалоги)
  - [Диалог подтверждения](#диалог-подтверждения)
  - [Просмотрщик текста](#просмотрщик-текста)
- [7. Переключение справочников: HTTP ↔ локальный](#7-переключение-справочников-http--локальный)
  - [Где хранятся локальные справочники](#где-хранятся-локальные-справочники)
  - [Переключить с локального на HTTP](#переключить-справочник-с-локального-на-http)
  - [Переключить с HTTP на локальный](#переключить-справочник-с-http-на-локальный)
  - [Фильтровать элементы справочника по окружению](#фильтровать-элементы-справочника-по-окружению)
  - [Добавить поиск по нескольким полям](#добавить-поиск-по-нескольким-полям)
  - [Изменить справочник у существующего поля](#изменить-справочник-у-существующего-поля)
- [8. Авторизация HTTP-справочников](#8-авторизация-http-справочников)
  - [Как работает авторизация](#как-работает-авторизация)
  - [Подключить токен к ресурсу](#подключить-токен-к-ресурсу)
  - [Добавить новый тип токена](#добавить-новый-тип-токена)
- [9. Кеширование HTTP-справочников](#9-кеширование-http-справочников)
  - [Настроить TTL для ресурса](#настроить-ttl-для-ресурса)
  - [Добавить кеширование для нового ресурса](#добавить-кеширование-для-нового-http-справочника)
  - [Отключить кеширование](#отключить-кеширование-для-ресурса)
  - [Принудительно сбросить кеш](#принудительно-сбросить-кеш-из-кода)
- [Структура проекта](#структура-проекта-справка)



---

## 1. Архитектура приложения: модули

### Структура навигации

Приложение **Gravitee Admin UI** состоит из трёх модулей, доступных с главного экрана (`HomeScreen`):

```
HomeScreen
├── 🔍 Поиск       → SearchScreen → SearchDetailScreen
├── 🚀 AutoDeploy UI → MainScreen → CategoryScreen → FormScreen
└── 📋 Операции    → OperationsScreen (заглушка)
```

Навигацией управляет `Application` (`ui/app.py`) через стек экранов:

- `app.navigate_to(ScreenClass, **kwargs)` — перейти на экран (предыдущий сохраняется в стек)
- `app.go_back()` — вернуться на предыдущий экран
- `app.go_home()` — вернуться на `HomeScreen`, стек очищается

---

### Добавить новый модуль на главный экран

**Шаг 1.** Создать файл экрана `ui/screens/my_module_screen.py`:

```python
import tkinter as tk
import ui.theme as theme
from ui.screens.base_screen import BaseScreen

class MyModuleScreen(BaseScreen):
    def _build(self) -> None:
        self._add_back_button()
        self._add_title("Мой модуль")
        # ... контент
```

**Шаг 2.** Добавить карточку модуля в `ui/screens/home_screen.py`:

```python
self._module_card(
    cards_wrap,
    icon="🛠",
    title="Мой модуль",
    desc="Описание модуля",
    screen_class=MyModuleScreen,
)
```

Карточка появится на главном экране автоматически — горизонтальный ряд подстраивается под количество карточек.

---

## 2. Модуль поиска

### Как работает поиск

Поиск работает напрямую через `ReferenceResolver` — тот же механизм, что и для справочников в формах. Данные загружаются по-окружению, фильтруются на стороне клиента.

```
SearchScreen
  └─ выбор раздела (АПИ / Приложения / ...)
       └─ SearchDetailScreen
            ├─ env picker: выбор Среды (TEST/REGRESS/PROD/ALL) × Сети (INT/EXT/INT&EXT)
            ├─ строка поиска
            └─ _rerun_search():
                 ├─ _resolve_envs() → список окружений (напр. ["test_int", "test_ext"])
                 ├─ reference_resolver.resolve(ref, env) для каждого окружения
                 ├─ фильтрация по search_keys (регистронезависимо)
                 ├─ дедупликация по (env, value_key)
                 └─ _show_results() → список карточек с бейджем окружения
```

Каждый результат отображается карточкой: `label_key` крупным текстом, остальные `search_keys` мелким, бейдж с окружением справа.

---

### Добавить новый раздел поиска

Открыть `ui/screens/search_screen.py` и добавить вызов `_choice_card()`:

```python
self._choice_card(
    cards_row,
    icon="🏗",
    title="Инфраструктура",
    desc="Поиск по ресурсам инфраструктуры",
    ref=ReferenceConfig(
        source="http",
        resource="infra_resources",   # должен быть в _URL_MAP
        value_key="id",
        label_key="name",
        search_keys=("name", "id", "type"),
    ),
)
```

Также добавить разделитель между карточками (пустой фрейм):

```python
tk.Frame(cards_row, bg=theme.C["bg"], width=20).pack(side=tk.LEFT)
```

Ресурс `infra_resources` нужно добавить в `_URL_MAP` в `handlers/http_reference_handler.py` (см. раздел 5).

---

### Изменить поля поиска у существующего раздела

В `ui/screens/search_screen.py` найти нужный вызов `_choice_card()` и изменить `ref`:

```python
# Добавить поиск по полю "description":
ref=ReferenceConfig(
    source="http",
    resource="gravitee_apis",
    value_key="id",
    label_key="name",
    search_keys=("name", "id", "context_path", "description"),  # добавить поле
),
```

В результатах дополнительные поля из `search_keys` (кроме `label_key`) отображаются в строке под заголовком через `·`.

---

### Настроить поля в детальной карточке

При клике на результат открывается карточка со всеми полями записи. Чтобы показывать только нужные поля — задать `detail_keys` в `ReferenceConfig`:

```python
ref=ReferenceConfig(
    source="http",
    resource="gravitee_apis",
    value_key="id",
    label_key="name",
    search_keys=("name", "id", "context_path"),
    detail_keys=("name", "id", "context_path", "state", "visibility", "updated_at"),
    # ↑ только эти поля будут показаны в карточке, в этом порядке
)
```

Если `detail_keys` не задан (по умолчанию `()`), отображаются **все поля** записи в том порядке, в котором они приходят из справочника.

Каждое поле в карточке:
- выделяется мышью (можно скопировать Ctrl+C)
- имеет кнопку `⎘` для копирования одним кликом

---

## 3. Добавить новую форму / изменить существующую

### Создать новую форму

**Шаг 1.** Создать файл в нужной категории:

```
forms/
  api/      ← формы категории "АПИ"
  apps/     ← "Приложения"
  other/    ← "Операции"
```

Пример: `forms/api/update_api_form.py`

```python
from typing import Any, Dict, List
from forms.base_form import BaseForm
from forms.fields import FieldDefinition, FieldType, ReferenceConfig

class UpdateApiForm(BaseForm):

    @property
    def form_id(self) -> str:
        return "api.update"           # уникальный ID, используется в реестре

    @property
    def title(self) -> str:
        return "Обновление АПИ"       # отображается в меню и заголовке формы

    @property
    def category(self) -> str:
        return "api"                  # "api" | "apps" | "other"

    @property
    def fields(self) -> List[FieldDefinition]:
        return [
            FieldDefinition(key="name", label="Название", field_type=FieldType.TEXT),
            # ... остальные поля
        ]

    def build_payload(self, form_data: Dict[str, Any]) -> Dict[str, Any]:
        # form_data — словарь {field.key: значение}
        return {"name": form_data.get("name", "")}

    def get_submit_endpoint(self, environment: str) -> str:
        urls = {"prod_int": "https://...", "test_int": "https://..."}
        return urls.get(environment, "")
```

**Шаг 2.** Зарегистрировать в `forms/loader.py`:

```python
from forms.api.update_api_form import UpdateApiForm

def register_all_forms() -> None:
    registry = FormRegistry()
    registry.register(UpdateApiForm())   # добавить одну строку
    # ...
```

Больше ничего менять не нужно — форма появится в меню автоматически.

---

### Добавить новую категорию

1. Добавить ключ в `config/categories.py`:

```python
CATEGORIES = {
    "api":      "АПИ",
    "apps":     "Приложения",
    "other":    "Операции",
    "infra":    "Инфраструктура",   # новая категория
}
CATEGORY_ORDER = ["api", "apps", "other", "infra"]
```

2. Создать папку `forms/infra/` с `__init__.py`.
3. В форме указать `category = "infra"`.

---

### Типы полей

| `FieldType`   | Виджет              | `.get()` возвращает |
|---------------|---------------------|---------------------|
| `TEXT`        | однострочный ввод   | `str`               |
| `TEXTAREA`    | многострочный ввод  | `str`               |
| `SELECT`      | выпадающий список   | `str` (value_key)   |
| `MULTISELECT` | список чекбоксов    | `List[str]`         |
| `CHECKBOX`    | одиночный чекбокс   | `bool`              |
| `NUMBER`      | числовой ввод       | `int`               |

Полный список параметров `FieldDefinition`:

```python
FieldDefinition(
    key="field_key",          # ключ в form_data
    label="Отображаемое имя",
    field_type=FieldType.TEXT,
    required=True,            # влияет на валидацию
    placeholder="Подсказка",  # серый текст в пустом поле
    default=None,             # начальное значение
    reference=None,           # ReferenceConfig для SELECT/MULTISELECT
    condition=None,           # FieldCondition для условного появления
)
```

---

### Условное поле (показать/скрыть при выборе другого)

```python
from forms.fields import FieldCondition

FieldDefinition(
    key="channel_type",
    label="Тип канала",
    field_type=FieldType.SELECT,
    required=False,                          # обязательность проверяется вручную в validate()
    reference=ReferenceConfig(...),
    condition=FieldCondition(
        field_key="ingress_type",            # ключ поля-триггера
        value="platformeco",                 # значение, при котором это поле показывается
    ),
)
```

Если поле скрыто — оно **не попадает в payload** и **не валидируется** базовым методом.
Для кастомной валидации условного поля — переопределить `validate()` в форме:

```python
def validate(self, form_data):
    errors = super().validate(form_data)
    if form_data.get("ingress_type") == "platformeco":
        if not form_data.get("channel_type"):
            errors.append('"Тип канала" обязателен для platformeco')
    return errors
```

---

### Изменить существующую форму

Все изменения — только в файле формы. Остальной код трогать не нужно.

| Что изменить               | Где                          |
|----------------------------|------------------------------|
| Поля формы                 | `fields` property            |
| URL по окружениям          | `get_submit_endpoint()`      |
| Структура JSON             | `build_payload()`            |
| Кастомная валидация        | `validate()`                 |
| HTTP метод (по умолч. POST)| переопределить `get_http_method()` → `"PUT"` |

---

## 4. Изменить обработку сабмита и конструирование JSON

### Как работает сабмит

> Чтобы изменить **куда** летит запрос — редактировать `get_submit_endpoint()` в файле формы.
> Чтобы изменить **что** отправляется — редактировать `build_payload()`.
> Оба метода описаны ниже.

```
FormScreen._on_submit()
    └─ _collect_form_data()              # собирает данные только видимых полей
    └─ SubmitService.submit()
            └─ form.validate()           # валидация
            └─ form.build_payload()      # конструирование JSON
            └─ EnvManager.get()          # берёт токен для выбранного окружения
            └─ HttpClient.post/put()     # HTTP запрос
    └─ (при успехе) navigate_to(ResultScreen)
            └─ form.get_result_config()  # заголовок и интервал опроса
            └─ form.build_result_content()  # отображает первичный ответ
            └─ (если poll_interval_ms)
                    └─ form.get_poll_endpoint()   # URL для GET-опроса
                    └─ form.build_poll_content()  # форматирует каждый ответ
```

---

### Изменить URL (куда летит запрос)

URL задаётся в `get_submit_endpoint()` внутри файла формы. Метод получает `environment` (ключ окружения) и возвращает нужный URL.

```python
_SUBMIT_URLS: Dict[str, str] = {
    "test_int":    "https://api.test-int.example.com/management/v2/apis",
    "test_ext":    "https://api.test-ext.example.com/management/v2/apis",
    "regress_int": "https://api.regress-int.example.com/management/v2/apis",
    "regress_ext": "https://api.regress-ext.example.com/management/v2/apis",
    "prod_int":    "https://api.prod-int.example.com/management/v2/apis",
    "prod_ext":    "https://api.prod-ext.example.com/management/v2/apis",
}

def get_submit_endpoint(self, environment: str) -> str:
    return _SUBMIT_URLS.get(environment, "")
```

Если метод вернёт пустую строку — `SubmitService` покажет ошибку, запрос отправлен не будет.

---

### Изменить структуру JSON (payload)

Редактировать `build_payload()` в файле конкретной формы.
`form_data` — словарь `{field.key: значение}` только по видимым полям.

```python
def build_payload(self, form_data: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "apiName":    form_data.get("name", ""),
        "ownerTeam":  form_data.get("owner", ""),
        "meta": {
            "category": form_data.get("category", ""),
            "path":     form_data.get("context_path", ""),
        },
        # Поле включается в payload только если оно было видимо и заполнено:
        **({"channelType": form_data["channel_type"]}
           if form_data.get("channel_type") else {}),
    }
```

---

### Изменить HTTP метод

```python
def get_http_method(self) -> str:
    return "PUT"   # по умолчанию "POST"
```

---

### Добавить дополнительные заголовки к запросу

```python
def get_submit_headers(self, environment: str) -> Dict[str, str]:
    return {"X-Custom-Header": "value"}
```

> **Примечание:** `SubmitService` пока не передаёт доп. заголовки в `HttpClient`.
> Чтобы они применялись, нужно добавить их передачу в `services/submit_service.py`:
>
> ```python
> extra = form.get_submit_headers(environment)
> # передать extra в self._client.post(endpoint, payload, headers=extra)
> ```
> и принять `headers` в `HttpClient.post()`.

---

## 5. Экран результата после сабмита

### Как работает экран результата

После успешной отправки `FormScreen` переходит на `ResultScreen` (`ui/screens/result_screen.py`).
Что показывается и как обновляется — определяется четырьмя переопределяемыми методами формы.

| Метод | Когда вызывается | По умолчанию |
|---|---|---|
| `get_result_config()` | один раз при открытии экрана | `ResultScreenConfig()` — без опроса |
| `build_result_content(env, response)` | сразу после перехода на экран | JSON-дамп ответа сервера |
| `get_poll_endpoint(env, response)` | перед каждым GET-запросом | `None` — опрос не выполняется |
| `build_poll_content(env, poll_response)` | после каждого успешного опроса | JSON-дамп ответа |

`response` — ответ первоначального POST/PUT. Из него можно извлечь ID задачи, jobId и т.п. для формирования URL опроса.

---

### Настроить заголовок и автообновление

Переопределить `get_result_config()` в форме:

```python
from forms.result_config import ResultScreenConfig

def get_result_config(self) -> ResultScreenConfig:
    return ResultScreenConfig(
        title="Статус деплоя",   # заголовок экрана (по умолч. — form.title)
        poll_interval_ms=5000,   # опрашивать каждые 5 секунд (None — без опроса)
    )
```

При включённом опросе на экране появляется:
- бейдж «↻ каждые N с» рядом с заголовком
- кнопка «⏸ Пауза / ▶ Возобновить»
- метка «Обновлено: HH:MM:SS» после каждого обновления

---

### Кастомный контент результата

Переопределить `build_result_content()`, чтобы показать только нужные поля вместо сырого JSON:

```python
def build_result_content(self, environment: str, response: Any) -> str:
    if response is None:
        return "Деплой успешно запущен."
    job_id  = response.get("jobId", "—")
    status  = response.get("status", "—")
    app     = response.get("appName", "—")
    return (
        f"Приложение:  {app}\n"
        f"Job ID:      {job_id}\n"
        f"Статус:      {status}\n"
    )
```

---

### Включить автоопрос (polling)

Нужно переопределить три метода:

```python
from typing import Any, Optional
from forms.result_config import ResultScreenConfig

def get_result_config(self) -> ResultScreenConfig:
    return ResultScreenConfig(poll_interval_ms=3000, title="Статус деплоя")

def get_poll_endpoint(self, environment: str, response: Any) -> Optional[str]:
    # Извлекаем jobId из первичного ответа
    job_id = (response or {}).get("jobId")
    if not job_id:
        return None
    urls = {
        "prod_int": "https://deploy.prod-int.example.com/jobs",
        "test_int": "https://deploy.test-int.example.com/jobs",
    }
    base = urls.get(environment, "")
    return f"{base}/{job_id}" if base else None

def build_poll_content(self, environment: str, poll_response: Any) -> str:
    status   = (poll_response or {}).get("status", "—")
    progress = (poll_response or {}).get("progress", "—")
    log      = (poll_response or {}).get("lastLog", "")
    return (
        f"Статус:    {status}\n"
        f"Прогресс:  {progress}\n\n"
        f"{log}"
    )
```

Опрос выполняется через `HttpClient.get()` с тем же Bearer-токеном, что и при отправке формы.
Если `get_poll_endpoint()` вернёт `None` или пустую строку — цикл пропускается, но следующий через N секунд всё равно запланируется.

---

## 6. UI-утилиты: диалоги

Все утилиты находятся в `ui/dialogs.py` и используют тему приложения (цвета, шрифты).
Импорт: `from ui.dialogs import show_info, show_error, show_warning, show_confirm, show_text_viewer`.

### Информационные диалоги

```python
from ui.dialogs import show_info, show_error, show_warning

# Информационное сообщение
show_info(self, "Готово", "Операция успешно выполнена.")

# Ошибка (длинный текст — прокрутка автоматически)
show_error(self, "Ошибка подключения", f"Не удалось соединиться:\n{exc}")

# Предупреждение
show_warning(self, "Внимание", "Поле 'Описание' не заполнено.")
```

Все три принимают `parent: tk.Widget` (обычно `self`), `title: str`, `body: str`.
Открываются как модальные окна (блокируют родительское окно до нажатия «ОК»).

---

### Диалог подтверждения

```python
from ui.dialogs import show_confirm

if show_confirm(self, "Подтверждение", "Удалить выбранный ресурс?"):
    # пользователь нажал «Да»
    self._do_delete()
```

Возвращает `True` («Да») или `False` («Нет» / закрыл крестиком).

---

### Просмотрщик текста

```python
from ui.dialogs import show_text_viewer
import json

# Показать JSON
show_text_viewer(self, "Ответ сервера", json.dumps(data, ensure_ascii=False, indent=2))

# Показать лог
show_text_viewer(self, "Лог выполнения", log_text, width=80, height=30)
```

Открывает модальное окно с прокручиваемым моноширинным текстом и кнопкой «Закрыть».

---

## 7. Переключение справочников: HTTP ↔ локальный

### Где хранятся локальные справочники

```
config/references/
    api_categories.json
    endpoint_types.json
    ingress_types.json
    channel_types.json
    applications.json    ← пример с полями name и azp
```

Формат файла — массив объектов:

```json
[
  {"id": "value1", "name": "Отображаемое имя 1"},
  {"id": "value2", "name": "Отображаемое имя 2"}
]
```

Или с обёрткой `{"items": [...]}` — оба формата поддерживаются.

---

### Переключить справочник с локального на HTTP

**В файле формы** изменить `source` с `"local"` на `"http"`:

```python
# Было:
ReferenceConfig(source="local", resource="applications.json", ...)

# Стало:
ReferenceConfig(source="http", resource="applications", ...)
#                                        ↑ ключ из _URL_MAP, не имя файла
```

**В `handlers/http_reference_handler.py`** добавить URL в `_URL_MAP`:

```python
_URL_MAP: Dict[str, Dict[str, str]] = {
    "applications": {
        "test_int":  "https://api.test-int.example.com/v1/apps",
        "test_ext":  "https://api.test-ext.example.com/v1/apps",
        "prod_int":  "https://api.prod-int.example.com/v1/apps",
        "prod_ext":  "https://api.prod-ext.example.com/v1/apps",
        # ... остальные окружения
    },
}
```

Если ответ сервера не является плоским массивом — добавить постпроцессор в `_RESPONSE_PROCESSORS`:

```python
_RESPONSE_PROCESSORS: Dict[str, Callable[[Any], List[Dict]]] = {
    "applications": lambda resp: resp.get("data", {}).get("items", []),
}
```

---

### Фильтровать элементы справочника по окружению

Для кастомной фильтрации **уже распакованного** списка элементов в зависимости от окружения используется `_FILTER_MAP` в `handlers/http_reference_handler.py`.

Сигнатура: `(environment: str, items: List[Dict]) -> List[Dict]`

Фильтр применяется **после** `_RESPONSE_PROCESSORS` и **до** записи в кеш — каждое окружение кешируется отдельно с уже отфильтрованными данными.

**Пример — разделить приложения по смысловой принадлежности:**

```python
_FILTER_MAP: Dict[str, Callable[[str, List[Dict]], List[Dict]]] = {
    "applications": lambda env, items: [
        item for item in items
        if ("regress" in item.get("name", "").lower()) == env.startswith("regress")
    ],
    # TEST_INT/TEST_EXT/PROD_*  → приложения без "regress" в имени
    # REGRESS_INT/REGRESS_EXT   → только приложения с "regress" в имени
}
```

**Конвейер целиком:**
```
HTTP-ответ → _RESPONSE_PROCESSORS (распаковка) → _FILTER_MAP (фильтр по env) → кеш → UI
```

Ключ `_FILTER_MAP` — `resource` из `ReferenceConfig` (тот же, что в `_URL_MAP`).
Ресурсы без записи в `_FILTER_MAP` не фильтруются.

---

### Переключить справочник с HTTP на локальный

**В файле формы**:

```python
ReferenceConfig(source="local", resource="my_reference.json", ...)
```

**Создать файл** `config/references/my_reference.json`:

```json
[
  {"id": "val1", "name": "Название 1"},
  {"id": "val2", "name": "Название 2"}
]
```

URL и постпроцессоры в `http_reference_handler.py` можно не трогать — обработчик не вызовется.

---

### Добавить поиск по нескольким полям

Поиск поддерживается в обоих типах полей выбора — **SELECT** и **MULTISELECT**.
Задаётся через `search_keys` в `ReferenceConfig`:

```python
ReferenceConfig(
    source="http",
    resource="gravitee_apis",
    value_key="id",
    label_key="name",
    search_keys=("name", "id", "context_path"),  # поля для поиска
)
```

**SELECT** (`search_keys` задан):
- Виджет: строка поиска + прокручиваемый список (6 строк)
- Поиск фильтрует по всем указанным полям одновременно
- Выделение сохраняется при фильтрации

**MULTISELECT** (`search_keys` задан):
- Отображаемая строка объединяет все поля: `"frontend  —  frontend-svc-001"`
- Живой поиск фильтрует по любому из указанных полей
- Отмеченные элементы остаются отмеченными при фильтрации

**Без `search_keys`** (оба типа):
- Поиск всё равно отображается, но работает только по `label_key`

---

### Изменить справочник у существующего поля

Все параметры справочника задаются в `reference=ReferenceConfig(...)` прямо в `FieldDefinition` внутри формы. Менять нужно только файл формы.

| Параметр      | Описание                                                          |
|---------------|-------------------------------------------------------------------|
| `source`      | `"local"` — JSON из `config/references/`, `"http"` — загрузка с сервера |
| `resource`    | для `local`: имя файла (`"applications.json"`); для `http`: ключ из `_URL_MAP` |
| `value_key`   | поле объекта, которое уходит в payload (обычно `"id"`)           |
| `label_key`   | поле объекта, отображаемое пользователю (обычно `"name"`)        |
| `search_keys` | поля для поиска и отображения в строке (необязательно)           |
| `detail_keys` | поля для детальной карточки поиска; `()` — показать все (необязательно) |

**Пример — сменить источник с локального на HTTP:**

```python
# Было:
reference=ReferenceConfig(
    source="local",
    resource="applications.json",
    value_key="id",
    label_key="name",
    search_keys=("name", "azp", "id"),
)

# Стало:
reference=ReferenceConfig(
    source="http",
    resource="applications",      # ключ из _URL_MAP
    value_key="id",
    label_key="name",
    search_keys=("name", "azp", "id"),
)
```

**Пример — сменить справочник на другой:**

```python
# Было: ссылался на приложения
reference=ReferenceConfig(
    source="http",
    resource="applications",
    value_key="id",
    label_key="name",
)

# Стало: ссылается на список АПИ из Gravitee
reference=ReferenceConfig(
    source="http",
    resource="gravitee_apis",
    value_key="id",
    label_key="name",
    search_keys=("name", "id", "context_path"),
)
```

Если нужного ресурса нет в `_URL_MAP` — добавить его по инструкции выше («Переключить справочник с локального на HTTP»).

---

## 8. Авторизация HTTP-справочников

### Как работает авторизация

Перед каждым HTTP-запросом `HttpReferenceHandler` смотрит тип токена для ресурса в `_AUTH_MAP` (файл `handlers/http_reference_handler.py`), берёт нужный токен из `.env` через `EnvManager` и устанавливает его на `HttpClient`.

Доступные типы авторизации:

| Тип        | Схема                | Ключи в `.env`                        | Когда использовать              |
|------------|----------------------|---------------------------------------|---------------------------------|
| `gravitee` | `Bearer <token>`     | `GRAVITEE_TOKEN_<ENV_KEY>`            | Справочники Gravitee API        |
| `tfs`      | `Bearer <token>`     | `TFS_TOKEN`                           | Справочники TFS/Azure DevOps    |
| `itsm`     | `Basic <b64>`        | `ITSM_LOGIN`, `ITSM_PASSWORD`         | Справочники ITSM                |
| *(нет)*    | без заголовка        | —                                     | Публичные эндпоинты             |

---

### Подключить токен к ресурсу

Открыть `handlers/http_reference_handler.py` и добавить строку в `_AUTH_MAP`:

```python
_AUTH_MAP: Dict[str, str] = {
    "gravitee_apis": "gravitee",   # уже есть
    "tfs_builds":    "tfs",        # ← новая строка
}
```

Ключ — `resource` из `ReferenceConfig` (тот же, что в `_URL_MAP`).
Значение — тип токена из таблицы выше.

Больше ничего менять не нужно — токен подставится автоматически при загрузке справочника.

---

### Добавить новый тип токена

Если нужна авторизация с другим токеном (не Gravitee и не TFS):

**Шаг 1.** Добавить ключ в `config/environments.py`:

```python
MY_SERVICE_TOKEN_KEY = "MY_SERVICE_TOKEN"

# Или per-env вариант:
def my_service_token_key(env_key: str) -> str:
    return f"MY_SERVICE_TOKEN_{env_key.upper()}"
```

**Шаг 2.** Добавить ветку в `_set_auth()` в `handlers/http_reference_handler.py`:

```python
def _set_auth(self, resource: str, environment: str) -> None:
    auth_type = _AUTH_MAP.get(resource)
    if auth_type == "gravitee":
        token = self._env_manager.get(gravitee_token_key(environment))
    elif auth_type == "tfs":
        token = self._env_manager.get(TFS_TOKEN_KEY)
    elif auth_type == "my_service":                          # ← новая ветка
        token = self._env_manager.get(MY_SERVICE_TOKEN_KEY)
    else:
        token = ""
    self._client.set_token(token)
```

**Шаг 3.** Добавить в `_AUTH_MAP`:

```python
_AUTH_MAP: Dict[str, str] = {
    "gravitee_apis":  "gravitee",
    "my_resource":    "my_service",   # ← новая строка
}
```

**Шаг 4.** Прописать креды в `.env`:

```
# Bearer-токен
MY_SERVICE_TOKEN=your-token-here

# Basic Auth (логин + пароль)
MY_SERVICE_LOGIN=user
MY_SERVICE_PASSWORD=secret
```

---

## 9. Кеширование HTTP-справочников

Загруженные данные хранятся в памяти и дублируются на диск в папке `cached/`. При повторном открытии формы сетевой запрос не делается — отдаётся кеш.

Локальные справочники (`source="local"`) не кешируются — они читаются с диска мгновенно.

Доступны три режима для каждого ресурса:

| Значение в `CACHE_TTL` | Поведение |
|---|---|
| *(отсутствует)* | кеш отключён, каждый раз свежий HTTP-запрос |
| `300` (любое число > 0) | кеш живёт N секунд, после — автоматически протухает |
| `TTL_INFINITE` (`-1`) | кеш не протухает, обновляется только кнопкой ↻ |

---

### Настроить TTL для ресурса

Открыть `config/reference_cache_config.py` и добавить строку:

```python
from config.reference_cache_config import TTL_INFINITE

CACHE_TTL: Dict[str, int] = {
    "gravitee_apis": TTL_INFINITE,  # обновляется только вручную
    "applications":  300,           # протухает через 5 минут
    "fast_dict":     60,            # протухает через 1 минуту
}
```

Ключ — `resource` из `ReferenceConfig` (тот же, что в `_URL_MAP`).

---

### Бесконечный TTL (обновление только вручную)

`TTL_INFINITE = -1` означает, что кеш не протухает автоматически.
Данные загружаются один раз и живут до тех пор, пока пользователь не нажмёт ↻.

```python
from config.reference_cache_config import TTL_INFINITE

CACHE_TTL: Dict[str, int] = {
    "gravitee_apis": TTL_INFINITE,
}
```

При нажатии ↻ появляется диалог с датой последнего обновления кеша и кнопками **Обновить** / **Отмена**. Это позволяет избежать случайной перезагрузки медленных справочников.

---

### Добавить кеширование для нового HTTP-справочника

1. Добавить URL в `_URL_MAP` в `handlers/http_reference_handler.py` (как обычно)
2. Добавить TTL в `config/reference_cache_config.py`:

```python
CACHE_TTL: Dict[str, int] = {
    "gravitee_apis":   TTL_INFINITE,
    "my_new_resource": 120,   # ← новая строка, 2 минуты
}
```

Больше ничего менять не нужно.

---

### Отключить кеширование для ресурса

Удалить строку ресурса из `CACHE_TTL`. При каждом открытии формы будет делаться свежий HTTP-запрос.

---

### Принудительно сбросить кеш из кода

`ReferenceCache` доступен как `app.reference_cache`:

```python
# Сбросить весь кеш
app.reference_cache.invalidate()

# Сбросить один ресурс во всех окружениях
app.reference_cache.invalidate("gravitee_apis")

# Сбросить один ресурс в конкретном окружении
app.reference_cache.invalidate("gravitee_apis", "prod_int")
```

---

## Структура проекта (справка)

```
autodeploy-ui-python/
├── config/
│   ├── categories.py              # названия категорий и их порядок
│   ├── environments.py            # список окружений и ключи .env токенов
│   ├── reference_cache_config.py  # ← TTL кеша для каждого HTTP-справочника
│   └── references/                # локальные JSON-справочники
├── core/
│   ├── env_manager.py             # чтение/запись .env (токены)
│   ├── http_client.py             # HTTP клиент (GET/POST/PUT/DELETE)
│   ├── reference_cache.py         # кеш HTTP-справочников (память + файлы cached/)
│   └── reference_resolver.py      # выбирает нужный обработчик справочника
├── forms/
│   ├── base_form.py               # абстрактный класс формы (+ методы экрана результата)
│   ├── result_config.py           # ← ResultScreenConfig: poll_interval_ms, title
│   ├── fields.py                  # FieldDefinition, FieldType, ReferenceConfig, FieldCondition
│   ├── registry.py                # реестр форм (Singleton)
│   ├── loader.py                  # ← регистрировать новые формы здесь
│   ├── api/                       # формы категории АПИ
│   ├── apps/                      # формы категории Приложения
│   └── other/                     # формы категории Операции
├── handlers/
│   ├── local_reference_handler.py # читает config/references/*.json
│   └── http_reference_handler.py  # ← URL, авторизация, _RESPONSE_PROCESSORS, _FILTER_MAP
├── services/
│   └── submit_service.py          # валидация → payload → HTTP запрос
├── cached/                        # файловый кеш HTTP-справочников (авто, не коммитить)
└── ui/
    ├── theme.py                   # цвета, шрифты, ttk-стили ← менять внешний вид здесь
    ├── app.py                     # DI-контейнер, навигация, Ctrl+A/C/V/X fix
    ├── dialogs.py                 # ← UI-утилиты: show_info/error/warning/confirm/text_viewer
    ├── widgets/
    │   └── field_factory.py       # виджеты полей: SELECT, MULTISELECT, TEXT и др.
    └── screens/
        ├── base_screen.py         # базовый класс экрана (_build, _add_title, _add_back_button)
        ├── home_screen.py         # ← главный экран: карточки модулей
        ├── search_screen.py       # ← поиск: выбор раздела (АПИ / Приложения / ...)
        ├── search_detail_screen.py # ← поиск: строка + env picker + результаты
        ├── operations_screen.py   # модуль операций (заглушка)
        ├── main_screen.py         # AutoDeploy UI: выбор окружения
        ├── category_screen.py     # выбор формы внутри категории
        ├── form_screen.py         # рендер полей, условная видимость, сабмит
        ├── result_screen.py       # ← экран результата: контент + автоопрос
        └── settings_screen.py     # токены и креды (.env)
```
