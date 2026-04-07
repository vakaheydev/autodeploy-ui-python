# Руководство разработчика — AutoDeploy UI

---

## 1. Добавить новую форму / изменить существующую

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

## 2. Изменить обработку сабмита и конструирование JSON

### Как работает сабмит

```
FormScreen._on_submit()
    └─ _collect_form_data()          # собирает данные только видимых полей
    └─ SubmitService.submit()
            └─ form.validate()       # валидация
            └─ form.build_payload()  # конструирование JSON
            └─ EnvManager.get()      # берёт токен для выбранного окружения
            └─ HttpClient.post/put() # HTTP запрос
```

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

### Изменить логику после успешной отправки

Переопределить в `FormScreen` не получится без наследования.
Логика находится в `services/submit_service.py` → `SubmitResult`.
Реакция UI на результат — в `ui/screens/form_screen.py` → `_on_submit()`.

---

## 3. Переключение справочников: HTTP ↔ локальный

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

### Добавить поиск по нескольким полям в MULTISELECT

```python
ReferenceConfig(
    source="local",            # или "http" — не важно
    resource="applications.json",
    value_key="id",
    label_key="name",
    search_keys=("name", "azp"),   # поля для поиска и отображения
)
```

При заданном `search_keys`:
- Отображаемая строка: `"frontend  —  frontend-svc-001"`
- Живой поиск фильтрует по любому из указанных полей
- Отмеченные элементы остаются отмеченными при фильтрации

---

## Структура проекта (справка)

```
autodeploy-ui-python/
├── config/
│   ├── categories.py           # названия категорий и их порядок
│   ├── environments.py         # список окружений и ключи .env токенов
│   └── references/             # локальные JSON-справочники
├── core/
│   ├── env_manager.py          # чтение/запись .env (токены)
│   ├── http_client.py          # HTTP клиент (GET/POST/PUT/DELETE)
│   └── reference_resolver.py  # выбирает нужный обработчик справочника
├── forms/
│   ├── base_form.py            # абстрактный класс формы
│   ├── fields.py               # FieldDefinition, FieldType, ReferenceConfig, FieldCondition
│   ├── registry.py             # реестр форм (Singleton)
│   ├── loader.py               # ← регистрировать новые формы здесь
│   ├── api/                    # формы категории АПИ
│   ├── apps/                   # формы категории Приложения
│   └── other/                  # формы категории Операции
├── handlers/
│   ├── local_reference_handler.py   # читает config/references/*.json
│   └── http_reference_handler.py    # ← добавлять URL справочников здесь
├── services/
│   └── submit_service.py       # валидация → payload → HTTP запрос
└── ui/
    ├── theme.py                # цвета, шрифты, ttk-стили ← менять внешний вид здесь
    ├── app.py                  # DI-контейнер, навигация
    └── screens/
        └── form_screen.py      # рендер полей, условная видимость, сабмит
```
