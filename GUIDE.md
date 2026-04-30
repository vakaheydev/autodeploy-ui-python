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
  - [Поле типа FILE](#поле-типа-file)
  - [Поле типа BLOCK: группа вложенных полей](#поле-типа-block-группа-вложенных-полей)
  - [Plural-поле: дублирование по кнопке «+»](#plural-поле-дублирование-по-кнопке-)
  - [Условное поле](#условное-поле-показатьскрыть-при-выборе-другого)
  - [Кастомные кнопки формы](#кастомные-кнопки-формы)
  - [Изменить существующую форму](#изменить-существующую-форму)
- [4. Изменить обработку сабмита и конструирование JSON](#4-изменить-обработку-сабмита-и-конструирование-json)
  - [Как работает сабмит](#как-работает-сабмит)
  - [Изменить URL (куда летит запрос)](#изменить-url-куда-летит-запрос)
  - [Изменить структуру JSON](#изменить-структуру-json-payload)
  - [Изменить HTTP метод](#изменить-http-метод)
  - [Добавить заголовки к запросу](#добавить-дополнительные-заголовки-к-запросу)
  - [Изменить тип авторизации](#изменить-тип-авторизации)
  - [Добавить диалог подтверждения перед отправкой](#добавить-диалог-подтверждения-перед-отправкой)
  - [Выполнить действие перед отправкой (pre_submit)](#выполнить-действие-перед-отправкой-pre_submit)
- [5. Экран результата после сабмита](#5-экран-результата-после-сабмита)
  - [Как работает экран результата](#как-работает-экран-результата)
  - [Настроить заголовок и автообновление](#настроить-заголовок-и-автообновление)
  - [Иконка статуса в заголовке](#иконка-статуса-в-заголовке)
  - [Кастомный контент результата](#кастомный-контент-результата)
  - [Включить автоопрос (polling)](#включить-автоопрос-polling)
- [6. UI-утилиты: диалоги](#6-ui-утилиты-диалоги)
  - [Информационные диалоги](#информационные-диалоги)
  - [Диалог подтверждения](#диалог-подтверждения)
  - [Просмотрщик текста](#просмотрщик-текста)
  - [Диалог ввода строки](#диалог-ввода-строки)
  - [Специализированные диалоги ввода](#специализированные-диалоги-ввода)
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
- [10. ITSM-интеграция: подтянуть данные из заявки](#10-itsm-интеграция-подтянуть-данные-из-заявки)
  - [Как это работает](#как-это-работает)
  - [Включить для формы](#включить-для-формы)
  - [Реализовать получение данных](#реализовать-получение-данных)
  - [Программная установка значений полей](#программная-установка-значений-полей)
- [11. Сервисы: GraviteeService, TfsService, ITSMService](#11-сервисы-graviteeservice-tfsservice-itsmservice)
- [12. Предыдущие запуски](#12-предыдущие-запуски)
  - [Как работает история запусков](#как-работает-история-запусков)
  - [Структура записи RunRecord](#структура-записи-runrecord)
  - [Обнаружение устаревших записей](#обнаружение-устаревших-записей)
  - [Восстановление формы из истории](#восстановление-формы-из-истории)
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

Детальная карточка элемента открывается по **правой кнопке мыши (ПКМ)** на элементе списка — это не меняет текущий выбор.

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

При ПКМ на результате открывается карточка со всеми полями записи. Чтобы показывать только нужные поля — задать `detail_keys` в `ReferenceConfig`:

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

| `FieldType`   | Виджет                               | `.get()` возвращает |
|---------------|--------------------------------------|---------------------|
| `TEXT`        | однострочный ввод                    | `str`               |
| `TEXTAREA`    | многострочный ввод                   | `str`               |
| `SELECT`      | выпадающий список с поиском          | `str` (value_key)   |
| `MULTISELECT` | список чекбоксов                     | `List[str]`         |
| `CHECKBOX`    | одиночный чекбокс (☐/☑)             | `bool`              |
| `NUMBER`      | числовой ввод                        | `int`               |
| `FILE`        | кнопка выбора файла + textarea       | `str` (содержимое)  |
| `BLOCK`       | группа вложенных полей               | `Dict[str, Any]`    |

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
    condition=None,           # lambda v: bool — предикат видимости поля
    file_type="",             # для FILE: расширение файла, напр. ".json"
    plural=False,             # включить кнопку "+" для дублирования поля
    plural_max=None,          # макс. кол-во экземпляров при plural=True
    block_fields=[],          # для BLOCK: список вложенных FieldDefinition
)
```

Параметр `default` работает для всех типов полей:

| Тип           | Что подставляется                                               |
|---------------|-----------------------------------------------------------------|
| `TEXT`        | строка; если задан и `placeholder` — показывается текст, не подсказка |
| `TEXTAREA`    | строка                                                          |
| `NUMBER`      | число (в том числе `0`)                                         |
| `CHECKBOX`    | `True` / `False`                                                |
| `SELECT`      | `value_key` элемента, который будет выбран изначально           |
| `MULTISELECT` | список `value_key` изначально отмеченных элементов              |
| `FILE`        | строка-содержимое (подставляется в textarea)                    |
| `BLOCK`       | словарь `{sub_key: value}` для предзаполнения вложенных полей  |

---

### Поле типа FILE

Отображает кнопку «Выбрать файл» и textarea. Пользователь может выбрать файл кнопкой (содержимое загрузится автоматически) или вставить/написать содержимое вручную.

```python
FieldDefinition(
    key="config",
    label="Конфигурация",
    field_type=FieldType.FILE,
    file_type=".json",    # фильтр в диалоге выбора файла
    required=True,
)
```

`form_data["config"]` в `build_payload()` содержит строку с содержимым файла:

```python
def build_payload(self, form_data):
    import json
    raw = form_data.get("config", "")
    return {"config": json.loads(raw)}   # парсить по необходимости
```

`file_type` принимает расширение с точкой (`.json`, `.yaml`) или без (`json`, `yaml`).
Если не задан — диалог открывается без фильтра.

---

### Поле типа BLOCK: группа вложенных полей

`BLOCK` объединяет несколько полей в визуальный блок. Поддерживает условную видимость вложенных полей и `plural` (дублирование всего блока целиком).

`.get()` возвращает `Dict[str, Any]` со значениями всех видимых вложенных полей.

**Пример — блок «Тарифный план»:**

```python
from forms.fields import FieldDefinition, FieldType, ReferenceConfig

FieldDefinition(
    key="plan",
    label="Тарифный план",
    field_type=FieldType.BLOCK,
    plural=True,
    plural_max=10,
    block_fields=[
        FieldDefinition(
            key="plan_type",
            label="Тип плана",
            field_type=FieldType.SELECT,
            required=True,
            reference=ReferenceConfig(
                source="local",
                resource="plan_types.json",
                value_key="id",
                label_key="name",
            ),
        ),
        FieldDefinition(
            key="jwt_type",
            label="Тип JWT",
            field_type=FieldType.SELECT,
            required=False,
            reference=ReferenceConfig(
                source="local",
                resource="jwt_types.json",
                value_key="id",
                label_key="name",
            ),
            # Показывается только когда plan_type == "JWT"
            condition=lambda v: v.get("plan_type") == "JWT",
        ),
    ],
)
```

Условная видимость (`condition`) внутри блока:
- пересчитывается при каждом изменении любого вложенного поля
- начальное состояние вычисляется сразу при открытии формы (поля с `default` учитываются)
- поля всегда отображаются в том порядке, в котором они объявлены в `block_fields`

**`build_payload()` — сбор блоков:**

```python
def build_payload(self, form_data):
    # Один блок — form_data["plan"] уже Dict[str, Any]
    plan = form_data.get("plan", {})

    # Несколько блоков (plural=True) — collect_plural возвращает List[Dict]
    plans = self.collect_plural(form_data, "plan")
    return {
        "plans": [
            {"type": p.get("plan_type"), "jwtType": p.get("jwt_type")}
            for p in plans
        ]
    }
```

**Структура `form_data` с BLOCK-полем:**

`form_data` остаётся плоским на верхнем уровне. Значение BLOCK-поля — вложенный словарь. Условные sub-поля, которые скрыты, в словарь не попадают.

```python
# Один блок, plan_type == "JWT" → jwt_type видим
form_data = {
    "plan": {
        "plan_type": "JWT",
        "jwt_type":  "old_idp",
    }
}

# Один блок, plan_type == "API_KEY" → jwt_type скрыт
form_data = {
    "plan": {
        "plan_type": "API_KEY",
        # jwt_type не включается
    }
}

# plural=True, пользователь добавил ещё два блока
form_data = {
    "plan":   {"plan_type": "JWT",     "jwt_type": "old_idp"},
    "plan_2": {"plan_type": "API_KEY"},
    "plan_3": {"plan_type": "JWT",     "jwt_type": "m2m_int"},
}

# collect_plural собирает все экземпляры в список
plans = self.collect_plural(form_data, "plan")
# → [
#     {"plan_type": "JWT",     "jwt_type": "old_idp"},
#     {"plan_type": "API_KEY"},
#     {"plan_type": "JWT",     "jwt_type": "m2m_int"},
# ]
```

**Ограничения:**
- `plural` у вложенных полей блока игнорируется (дублируется весь блок)
- HTTP-справочники в `block_fields` загружаются без диалога «Загрузка»

---

### Plural-поле: дублирование по кнопке «+»

При `plural=True` в заголовке поля появляется кнопка «+». Каждое нажатие добавляет ещё один экземпляр того же поля под предыдущим. У каждой копии есть кнопка «×» для удаления.

```python
FieldDefinition(
    key="cert",
    label="Сертификат",
    field_type=FieldType.FILE,
    file_type=".pem",
    plural=True,
    plural_max=5,    # не более 5 экземпляров; None — без ограничения
)
```

Ключи в `form_data`:

| Экземпляр      | Ключ      |
|----------------|-----------|
| Первый (базовый) | `cert`  |
| Второй         | `cert_2`  |
| Третий         | `cert_3`  |
| …              | …         |

Когда количество экземпляров достигает `plural_max` — кнопка «+» скрывается. При удалении любого экземпляра кнопка возвращается.

`plural` совместим с любым типом поля.

**Сбор значений в `build_payload()` — утилита `collect_plural`:**

```python
def build_payload(self, form_data):
    # Собирает cert, cert_2, cert_3, … — в порядке добавления,
    # пропуская пустые значения
    certs = self.collect_plural(form_data, "cert")
    return {"certificates": certs}
```

`collect_plural(form_data, base_key) → List[Any]`:
- Возвращает список непустых значений всех экземпляров группы
- Пустые строки, `None` и пустые списки пропускаются
- Порядок: базовый → `_2` → `_3` → …
- Если ни одного экземпляра нет — вернёт `[]`

---

### Условное поле (показать/скрыть при выборе другого)

`condition` — предикат `Callable[[Dict[str, Any]], bool]`.
Инпут — словарь `{field.key: текущее_значение}` всех полей формы (тот же формат, что `form_data` в `build_payload`).
Поле показывается когда предикат возвращает `True`, скрывается при `False`.
Пересчитывается при изменении любого поля формы — **в том числе при начальной загрузке**: если поле имеет `default`, условие вычисляется сразу.

Условные поля всегда отображаются в том порядке, в котором они объявлены в `fields`.

**Простое условие — одно поле:**

```python
FieldDefinition(
    key="channel_type",
    label="Тип канала",
    field_type=FieldType.SELECT,
    required=False,                          # обязательность проверяется вручную в validate()
    reference=ReferenceConfig(...),
    condition=lambda v: v.get("ingress_type") == "platformeco",
)
```

**AND / OR:**

```python
# Показать если тип "jwt" И окружение содержит "prod"
condition=lambda v: v.get("plan_type") == "jwt" and "prod" in v.get("env", ""),

# Показать если один из двух типов
condition=lambda v: v.get("ingress_type") in ("platformeco", "nginx"),
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

### Кастомные кнопки формы

Форма может объявить дополнительные кнопки, которые отображаются в футере рядом с «Отправить». Это удобно для дополнительных действий: проверить АПИ, загрузить данные из внешней системы, запустить валидацию и т.п.

**Объявить кнопки — переопределить `get_custom_buttons()` в форме:**

```python
from forms.base_form import BaseForm, CustomButton
from typing import Callable, Dict, Any, List

class CreateApiForm(BaseForm):

    def get_custom_buttons(self) -> List[CustomButton]:
        return [
            CustomButton(
                label="Заполнить из Gravitee",
                handler=self._on_fill_from_gravitee,
                style="Secondary",   # "Primary" | "Secondary" (по умолч. "Secondary")
            ),
        ]

    def _on_fill_from_gravitee(self, environment: str) -> None:
        # self.screen — FormScreen: parent для диалогов + apply_form_data
        # self.gravitee_service / self.itsm_service доступны здесь
        data = self.gravitee_service.get_api_defaults(environment)
        self.screen.apply_form_data({
            "api_name":     data.get("name", ""),
            "context_path": data.get("contextPath", ""),
        })
```

**Сигнатура `CustomButton`:**

```python
@dataclass
class CustomButton:
    label:   str
    handler: Callable[[str, Callable[[Dict[str, Any]], List[str]]], None]
    style:   str = "Secondary"
```

`handler` вызывается с тремя аргументами:
- `environment: str` — текущий ключ окружения (`"test_int"`, `"prod_ext"`, …)
- `parent: tk.Widget` — виджет `FormScreen`; передавать в любой диалог из `ui.dialogs` как первый аргумент
- `apply_form_data: Callable[[Dict[str, Any]], List[str]]` — метод предзаполнения формы (см. раздел ниже)

Кнопки отображаются правее стандартных («Отправить», «Просмотр JSON», «Подтянуть из заявки») в том порядке, в котором возвращены из `get_custom_buttons()`.

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
| Дополнительные кнопки      | `get_custom_buttons()`       |

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
    └─ (при успехе) run_storage.save()   # сохраняет данные в историю запусков
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

### Изменить тип авторизации

По умолчанию все формы используют Gravitee Bearer-токен. Переопределить `get_auth_type()`:

```python
def get_auth_type(self) -> str:
    return "tfs"   # Bearer TFS_TOKEN
```

| Значение | Авторизация |
|---|---|
| `"gravitee"` | Bearer `GRAVITEE_TOKEN_<ENV_KEY>` (по умолчанию) |
| `"tfs"` | Bearer `TFS_TOKEN` |
| `"itsm"` | Basic `ITSM_LOGIN:ITSM_PASSWORD` |
| `"none"` | без авторизации |

Токены и логин/пароль берутся из `.env` через `EnvManager`.

---

### Добавить диалог подтверждения перед отправкой

Включить для необратимых операций — переопределить `confirm_submit()`:

```python
def confirm_submit(self) -> bool:
    return True
```

При нажатии «Отправить» откроется окно с методом, URL, окружением и payload.
Форма отправится только при подтверждении.

**Кастомный текст подтверждения** — переопределить `build_confirm_text()`:

```python
def build_confirm_text(
    self, environment: str, endpoint: str, method: str, payload: Dict[str, Any]
) -> str:
    app_name = payload.get("appName", "—")
    return (
        f"Вы собираетесь задеплоить приложение «{app_name}»\n"
        f"в окружение {environment.upper()}.\n\n"
        f"URL:  {endpoint}\n"
        f"Метод: {method}"
    )
```

По умолчанию показывается: метод, URL, окружение и полный JSON payload.

---

### Выполнить действие перед отправкой (pre_submit)

`pre_submit()` вызывается **после** сборки payload и **до** HTTP-запроса. По умолчанию ничего не делает.

Переопределить для любых побочных действий: запись файлов, git-операции, логирование, нотификации, проверка внешних условий.

```python
def pre_submit(
    self,
    form_data: Dict[str, Any],
    payload: Dict[str, Any],
    environment: str,
) -> None:
    # form_data  — исходные значения полей {field.key: value}
    # payload    — собранный JSON-словарь (можно изменить через payload.update(...))
    # environment — ключ текущего окружения, напр. "prod_int"
    import subprocess, json, pathlib

    repo = pathlib.Path("/path/to/repo")
    config_file = repo / "config.json"
    config_file.write_text(json.dumps(payload, indent=2, ensure_ascii=False))

    subprocess.run(["git", "-C", str(repo), "add", str(config_file)], check=True)
    subprocess.run(["git", "-C", str(repo), "commit", "-m", f"update config [{environment}]"], check=True)
    subprocess.run(["git", "-C", str(repo), "push"], check=True)
```

Если метод бросает исключение — **сабмит прерывается**, HTTP-запрос не отправляется, пользователю показывается диалог ошибки с текстом исключения.

> **Порядок выполнения:**
> ```
> validate() → get_submit_endpoint() → set_auth() → build_payload() → pre_submit() → HTTP-запрос
> ```

---

## 5. Экран результата после сабмита

### Как работает экран результата

После успешной отправки `FormScreen` переходит на `ResultScreen` (`ui/screens/result_screen.py`).
Что показывается и как обновляется — определяется переопределяемыми методами формы.

| Метод | Когда вызывается | По умолчанию |
|---|---|---|
| `get_result_config()` | один раз при открытии экрана | `ResultScreenConfig()` — без опроса |
| `build_result_content(env, response)` | сразу после перехода на экран | JSON-дамп ответа сервера |
| `get_result_status(env, response)` | сразу после перехода на экран | `ResultStatus.PENDING` |
| `get_poll_endpoint(env, response)` | перед каждым GET-запросом | `None` — опрос не выполняется |
| `build_poll_content(env, poll_response)` | после каждого успешного опроса | JSON-дамп ответа |
| `get_poll_status(env, poll_response)` | после каждого успешного опроса | `ResultStatus.WAITING` |
| `should_continue_polling(env, poll_response)` | после каждого успешного опроса | `True` — продолжать |

`response` — ответ первоначального POST/PUT. Из него можно извлечь ID задачи, jobId и т.п. для формирования URL опроса.

Авторизация poll-запросов — та же, что задана в `get_auth_type()` формы.

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
- кнопки «⏸ Пауза / ▶ Возобновить» и «⏹ Стоп»
- метка «Обновлено: HH:MM:SS» после каждого обновления

«⏹ Стоп» безвозвратно останавливает опрос. Возобновить можно только переотправив форму.

---

### Иконка статуса в заголовке

Рядом с заголовком отображается цветная иконка, отражающая текущее состояние операции:

| `ResultStatus` | Иконка | Цвет | Смысл |
|---|---|---|---|
| `PENDING` | ◷ | серый | форма принята, ожидает обработки |
| `WAITING` | ⏳ | оранжевый | процесс идёт, опрос продолжается |
| `SUCCESS` | ✓ | зелёный | операция завершена успешно |
| `ERROR` | ✗ | красный | ошибка |

Статус после первичного ответа задаёт `get_result_status()`, после каждого опроса — `get_poll_status()`.
При ошибке poll-запроса статус автоматически ставится в `ERROR`.

```python
from forms.result_config import ResultStatus

def get_result_status(self, environment: str, response: Any) -> ResultStatus:
    # Начальный ответ содержит статус — можно сразу показать итог
    if (response or {}).get("status") == "success":
        return ResultStatus.SUCCESS
    return ResultStatus.PENDING

def get_poll_status(self, environment: str, poll_response: Any) -> ResultStatus:
    status = (poll_response or {}).get("status", "")
    if status == "success":
        return ResultStatus.SUCCESS
    if status == "error":
        return ResultStatus.ERROR
    return ResultStatus.WAITING
```

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

```python
from typing import Any, Optional
from forms.result_config import ResultScreenConfig, ResultStatus

def get_result_config(self) -> ResultScreenConfig:
    return ResultScreenConfig(poll_interval_ms=3000, title="Статус деплоя")

def get_poll_endpoint(self, environment: str, response: Any) -> Optional[str]:
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

def get_poll_status(self, environment: str, poll_response: Any) -> ResultStatus:
    match (poll_response or {}).get("status", ""):
        case "success": return ResultStatus.SUCCESS
        case "error":   return ResultStatus.ERROR
        case _:         return ResultStatus.WAITING

def should_continue_polling(self, environment: str, poll_response: Any) -> bool:
    # Остановить опрос когда задача завершена (успешно или с ошибкой)
    return (poll_response or {}).get("status") not in ("success", "error")
```

Если `get_poll_endpoint()` вернёт `None` или пустую строку — цикл пропускается, но следующий через N секунд всё равно запланируется.
Если `should_continue_polling()` вернёт `False` — опрос останавливается автоматически (эквивалент нажатия «⏹ Стоп»).

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

### Диалог ввода строки

`ask_string` — универсальный диалог для запроса любой строки у пользователя.

```python
from ui.dialogs import ask_string

value = ask_string(
    parent,                        # tk.Widget — родительское окно
    title="Создать ветку",         # заголовок окна
    prompt="Введите имя ветки",    # текст над полем ввода
    confirm_text="Создать",        # текст кнопки подтверждения (по умолч. «Подтвердить»)
)
if value is not None:
    # пользователь ввёл что-то и подтвердил
    ...
```

Возвращает `str` (непустая введённая строка) или `None` (отменил / закрыл / ввёл пустое).
Нажатие Enter подтверждает ввод — эквивалентно кнопке подтверждения.

---

### Специализированные диалоги ввода

Специализированные диалоги — тонкие обёртки над `ask_string` с предустановленными параметрами:

| Функция | Заголовок | Подсказка | Кнопка |
|---|---|---|---|
| `ask_ticket_id(parent)` | «Подтянуть из заявки» | «Введите номер заявки» | «Подтянуть» |

**Добавить новый специализированный диалог** — одна функция в `ui/dialogs.py`:

```python
def ask_branch_name(parent: tk.Widget) -> Optional[str]:
    """Диалог ввода имени git-ветки."""
    return ask_string(parent, "Git Push", "Введите имя ветки", confirm_text="Push")
```

`ask_ticket_id` используется **автоматически** при нажатии «⬇ Подтянуть из заявки» — вручную вызывать не нужно.

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

## 10. ITSM-интеграция: подтянуть данные из заявки

### Как это работает

При включённой опции `itsm_support` на экране формы появляется кнопка **«⬇ Подтянуть из заявки»**. При нажатии:

1. Открывается модальное окно «Введите номер заявки» с полем ввода
2. После ввода номера и нажатия «Подтянуть» (или Enter) — открывается окно «Подтягиваем данные…»
3. В фоновом потоке вызывается `form.fetch_from_itsm(environment, ticket_id)`
4. По завершении:
   - **Успех** — значения подставляются в поля формы, открывается диалог со списком заполненных полей
   - **Ошибка** — открывается диалог с текстом исключения

Кнопка работает независимо от «Отправить» — позволяет сначала заполнить форму из заявки, потом скорректировать вручную.

---

### Включить для формы

Переопределить свойство `itsm_support` в классе формы:

```python
@property
def itsm_support(self) -> bool:
    return True
```

По умолчанию `False` — кнопка не отображается.

---

### Реализовать получение данных

Переопределить `fetch_from_itsm()`. Метод вызывается в фоновом потоке, поэтому можно делать HTTP-запросы без блокировки UI. Должен вернуть словарь `{field_key: value}`.

**Ключи словаря должны совпадать с `field.key` полей формы.** Лишние ключи игнорируются.

```python
def fetch_from_itsm(self, environment: str, ticket_id: str) -> Dict[str, Any]:
    # environment — текущий ключ окружения, напр. "prod_int"
    # ticket_id   — номер заявки, введённый пользователем в диалоге
    response = self.itsm_service.get_ticket(environment, ticket_id)
    return {
        "app_name":  response.get("appName", ""),
        "namespace": response.get("targetNamespace", ""),
        "env":       response.get("targetEnv", ""),
    }
```

Если метод бросит исключение — UI покажет диалог с ошибкой, форма останется в исходном состоянии.

---

### Программная установка значений полей: apply_form_data

`FormScreen.apply_form_data(data: Dict[str, Any]) -> List[str]` — единый публичный метод предзаполнения формы.

**Контракт входных данных:**

```python
data = {
    "field_key": value,   # ключ = field.key из FieldDefinition
    "field_2":   value2,  # plural-копии: base_2, base_3 — создаются автоматически
    ...
}
```

Ключи, для которых не нашлось виджета, молча пропускаются.
Возвращает `List[str]` — список ключей, по которым значение **было применено**.

**Типы value по типам полей:**

| `FieldType`   | Тип `value`          | Поведение                                              |
|---------------|----------------------|--------------------------------------------------------|
| `TEXT`        | `str`                | Подставляет текст, убирает плейсхолдер                 |
| `TEXTAREA`    | `str`                | Заменяет всё содержимое                                |
| `NUMBER`      | `int` / `str`        | Устанавливает число                                    |
| `CHECKBOX`    | `bool`               | Устанавливает состояние чекбокса                       |
| `SELECT`      | `str` (value_key)    | Выбирает элемент по значению, сохраняет фильтр         |
| `MULTISELECT` | `List[str]`          | Отмечает совпадающие элементы, снимает остальные       |
| `BLOCK`       | `Dict[str, Any]`     | Рекурсивно устанавливает значения вложенных полей      |

**Когда вызывается автоматически:**

| Сценарий | Источник данных | Кто вызывает |
|---|---|---|
| Восстановление из истории | `RunRecord.form_data` | `FormScreen._render_fields` через `initial_data=` |
| Заполнение из ITSM-заявки | результат `fetch_from_itsm()` | `FormScreen._on_fetch_from_itsm` |

**Связь `fetch_from_itsm` → `apply_form_data`:**

Словарь, который возвращает `fetch_from_itsm`, напрямую передаётся в `apply_form_data`. Поэтому ключи словаря **должны совпадать с `field.key`** нужных полей:

```python
def fetch_from_itsm(self, environment: str, ticket_id: str) -> Dict[str, Any]:
    response = self.itsm_service.get_ticket(environment, ticket_id)
    return {
        # ключи = field.key из self.fields
        "app_name":  response.get("appName", ""),
        "namespace": response.get("targetNamespace", ""),
        "replicas":  response.get("replicaCount", 1),    # int для NUMBER
        "is_public": response.get("publicAccess", False), # bool для CHECKBOX
    }
    # FormScreen сам вызовет apply_form_data(этот_словарь)
    # и покажет диалог со списком заполненных полей
```

**Вызов из кастомной кнопки:**

Хендлер получает `parent` — его можно передавать напрямую в любой диалог из `ui.dialogs`:

```python
import threading
from ui.dialogs import ask_string, show_error, show_info

def _on_fill(self, environment: str, parent, apply_form_data) -> None:
    # Спросить у пользователя строку прямо из хендлера
    api_id = ask_string(parent, "Загрузить из Gravitee", "Введите ID АПИ", confirm_text="Загрузить")
    if api_id is None:
        return  # пользователь отменил

    def _worker():
        try:
            data = self.gravitee_service.get_api(environment, api_id)
            apply_form_data({
                "app_name": data["name"],
                "replicas": data["replicaCount"],
            })
        except Exception as exc:
            show_error(parent, "Ошибка", str(exc))

    threading.Thread(target=_worker, daemon=True).start()
```

`ask_string` вызывается **до** запуска потока — он модальный и блокирует до ответа пользователя. Фоновый поток запускается уже с готовым значением.

---

## 11. Сервисы: GraviteeService, TfsService, ITSMService

Все три сервиса создаются в `Application` (`ui/app.py`) и доступны формам через атрибуты `BaseForm`:

| Атрибут формы           | Класс сервиса     | Файл                          |
|-------------------------|-------------------|-------------------------------|
| `self.gravitee_service` | `GraviteeService` | `services/gravitee_service.py` |
| `self.itsm_service`     | `ITSMService`     | `services/itsm_service.py`    |
| `self.tfs_service`      | `TfsService`      | `services/tfs_service.py`     |

Атрибуты устанавливаются `FormScreen` перед открытием формы — доступны в `fetch_from_itsm()`, `pre_submit()`, обработчиках кастомных кнопок и любых других методах формы.

**Добавить метод в GraviteeService:**

```python
# services/gravitee_service.py
class GraviteeService:
    def __init__(self, env_manager: EnvManager, http_client: HttpClient) -> None:
        self._env_manager = env_manager
        self._http_client = http_client

    def check_api(self, environment: str, api_id: str) -> Dict[str, Any]:
        # Установить авторизацию
        token = self._env_manager.get(gravitee_token_key(environment))
        self._http_client.set_token(token)
        # Сделать запрос
        url = f"https://api.{environment}.example.com/management/v2/apis/{api_id}"
        return self._http_client.get(url)
```

**Использование в форме:**

```python
def _on_check_api(self, environment: str) -> None:
    api_id = self._field_widgets["api_id"].get()
    result = self.gravitee_service.check_api(environment, api_id)
    from ui.dialogs import show_info
    show_info(None, "Проверка АПИ", f"Статус: {result.get('state', '—')}")
```

---

## 12. Предыдущие запуски

### Как работает история запусков

После каждого **успешного** сабмита формы данные автоматически сохраняются в `data/runs.json`. На главном экране AutoDeploy UI доступна кнопка **«🕑 Предыдущие запуски»**, открывающая `RunsScreen`.

`RunsScreen` отображает список карточек: название формы, окружение, дата/время, статус актуальности. Записи отображаются в обратном хронологическом порядке (новые сверху).

Хранится не более 100 последних запусков — старые автоматически вытесняются.

---

### Структура записи RunRecord

```python
@dataclass
class RunRecord:
    run_id:          str              # UUID записи
    form_id:         str              # form.form_id
    environment:     str              # напр. "prod_int"
    timestamp:       float            # time.time() на момент сабмита
    form_data:       Dict[str, Any]   # значения полей на момент сабмита
    fields_snapshot: Dict[str, str]   # {field.key: field_type.value} — снимок структуры
```

`fields_snapshot` используется для обнаружения устаревших записей — он сохраняется вместе с данными и сравнивается с текущей структурой формы при загрузке истории.

---

### Обнаружение устаревших записей

Запись считается **устаревшей** (`Устарело`) если:
- форма с `run.form_id` больше не зарегистрирована в `FormRegistry`, или
- текущий `{f.key: f.field_type.value}` для полей формы не совпадает с `run.fields_snapshot`

Это улавливает переименование полей и смену типов. Устаревшие записи отображаются с бейджем «Устарело», кнопка «Восстановить →» для них недоступна.

```python
# Логика проверки (runs_screen.py)
def _is_stale(run: RunRecord) -> bool:
    try:
        form = FormRegistry().get(run.form_id)
        current = {f.key: f.field_type.value for f in form.fields}
        return current != run.fields_snapshot
    except Exception:
        return True   # форма не найдена → устарело
```

---

### Восстановление формы из истории

При нажатии «Восстановить →»:
1. Устанавливается `current_environment` из `run.environment`
2. Открывается `FormScreen` с `form_id=run.form_id` и `initial_data=run.form_data`
3. `FormScreen` заполняет все поля из `initial_data` **до** вычисления условий — условные поля отображаются корректно с учётом восстановленных значений

`RunStorage` доступен как `app.run_storage`:

```python
# Сохранить запись (вызывается автоматически после успешного сабмита)
app.run_storage.save(
    form_id=form.form_id,
    environment=environment,
    form_data=form_data,
    fields_snapshot={f.key: f.field_type.value for f in form.fields},
)

# Загрузить все записи
records: List[RunRecord] = app.run_storage.load_all()

# Удалить запись по ID
app.run_storage.delete(run_id)
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
│   ├── reference_resolver.py      # выбирает нужный обработчик справочника
│   └── run_storage.py             # ← история запусков форм (data/runs.json)
├── data/
│   └── runs.json                  # файл истории запусков (авто, не коммитить)
├── forms/
│   ├── base_form.py               # абстрактный класс формы + CustomButton
│   ├── result_config.py           # ← ResultScreenConfig: poll_interval_ms, title
│   ├── fields.py                  # FieldDefinition, FieldType, ReferenceConfig, Condition
│   ├── registry.py                # реестр форм (Singleton)
│   ├── loader.py                  # ← регистрировать новые формы здесь
│   ├── api/                       # формы категории АПИ
│   ├── apps/                      # формы категории Приложения
│   └── other/                     # формы категории Операции
├── handlers/
│   ├── local_reference_handler.py # читает config/references/*.json
│   └── http_reference_handler.py  # ← URL, авторизация, _RESPONSE_PROCESSORS, _FILTER_MAP
├── services/
│   ├── submit_service.py          # валидация → payload → HTTP запрос
│   ├── gravitee_service.py        # ← сервис Gravitee API (доступен в формах)
│   ├── itsm_service.py            # ← сервис ITSM (доступен в формах)
│   └── tfs_service.py             # ← сервис TFS/Azure DevOps (доступен в формах)
├── cached/                        # файловый кеш HTTP-справочников (авто, не коммитить)
└── ui/
    ├── theme.py                   # цвета, шрифты, ttk-стили ← менять внешний вид здесь
    ├── app.py                     # DI-контейнер, навигация, Ctrl+A/C/V/X fix
    ├── dialogs.py                 # ← UI-утилиты: show_info/error/warning/confirm/text_viewer/ask_string + обёртки
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
        ├── runs_screen.py         # ← экран истории запусков
        ├── result_screen.py       # ← экран результата: контент + автоопрос
        └── settings_screen.py     # токены и креды (.env)
```
