# Справочники и глобальный поиск

## Модель данных

Форма объявляет только логический контракт справочника:

```python
ReferenceConfig(
    source="corp_http",
    resource="gravitee_apis",
    value_key="id",
    label_key="name",
    search_keys=("context_path", "name", "id"),
    detail_keys=("name", "context_path", "owner"),
)
```

- `source` выбирает handler;
- `resource` — private logical resource key, а не URL;
- `value_key` хранится в values/payload;
- `label_key` показывается как основная подпись;
- `search_keys` задаёт поля фильтра в объявленном порядке;
- `detail_keys` ограничивает read-only карточку элемента; пустой tuple публикует
  все non-secret поля item, поэтому для private HTTP данных лучше указывать его
  явно;
- `required_params` перечисляет параметры, без которых load не запускается.

`SELECT` возвращает один scalar `value_key`, `MULTISELECT` — массив. Полный
dictionary item не хранится в форме и повторно разрешается server-side.

Frontend показывает в filter placeholder поля `search_keys`, выводит их рядом с
элементом, сохраняет выбранные значения сверху выдачи и открывает `detail_keys`
в read-only карточке по правому клику. Нажатие на значение в карточке копирует
его. Эти UI-возможности не меняют storage contract.

## Corporate handler

Не изменяйте public URL maps. Создайте собственный source и handler:

```python
from typing import Any

from handlers.base_reference_handler import BaseReferenceHandler


class CorporateReferenceHandler(BaseReferenceHandler):
    def __init__(self, env_manager, http_client, cache):
        self.env = env_manager
        self.http = http_client
        self.cache = cache

    def supports(self, config) -> bool:
        return config.source in {"corp_http", "corp_local"}

    def load(
        self,
        config,
        environment: str = "",
        extra_params: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        if config.source == "corp_local":
            return self._load_packaged_json(config.resource)
        return self._load_remote(config.resource, environment, extra_params or {})


def create_handlers(env_manager, http_client, cache):
    return [CorporateReferenceHandler(env_manager, http_client, cache)]
```

Каждый returned item обязан содержать `value_key` и `label_key`. Handler должен:

- выбирать endpoint/auth по `resource` и explicit `environment`;
- ограничивать timeout и response size;
- преобразовывать vendor response в `list[dict]`;
- не возвращать credentials, auth headers и confidential fields;
- логировать resource/environment/status/error type без секретов;
- при ожидаемой недоступности вернуть `[]` и записать диагностическую причину;
- быть thread-safe или не хранить mutable request state.

Private handlers добавляются перед public local/http fallback. Не используйте
source `http`, если хотите гарантированно избежать public placeholder map.

Подключение:

```dotenv
AUTODEPLOY_REFERENCE_HANDLER_FACTORY=corp_autodeploy.references:create_handlers
```

## Private local dictionaries

JSON кладётся в `src/corp_autodeploy/reference_data/` и включается как package
data. Загружайте его через `importlib.resources`, а не через current working
directory:

```python
import json
from importlib.resources import files


def load_json(name: str):
    root = files("corp_autodeploy.reference_data")
    return json.loads(root.joinpath(name).read_text(encoding="utf-8"))
```

Package data не является местом для secrets. Маленький local reference может
быть встроен server runtime в form document, только если он укладывается в
public limits (по умолчанию не более 99 items и 64 KiB). Большие и remote lists
всегда загружаются через paged options endpoint.

## Зависимые справочники

```python
FieldDefinition(
    key="api",
    label="API",
    field_type=FieldType.SELECT,
    reference=ReferenceConfig(
        source="corp_http",
        resource="gravitee_apis",
        value_key="id",
        label_key="name",
        search_keys=("context_path", "name"),
        detail_keys=("id", "name", "context_path"),
    ),
),
FieldDefinition(
    key="methods",
    label="Методы",
    field_type=FieldType.MULTISELECT,
    reference=ReferenceConfig(
        source="corp_http",
        resource="api_methods",
        value_key="id",
        label_key="name",
        required_params=("api",),
    ),
    depends_on="api",
    depends_on_field="id",
),
```

Алгоритм runtime:

1. читает stored value поля `api`;
2. если задан `depends_on_field`, разрешает полный parent item и берёт `item[id]`;
3. вызывает child handler с `extra_params={"api": resolved_value}`;
4. если любой `required_params` пуст, handler не вызывается и список пуст;
5. при смене parent child value проходит повторную reference validation.

Ключ в `extra_params` всегда равен `depends_on`, не `depends_on_field`. Если
parent value уже является dict, поле берётся прямо из него. Condition и
`depends_on` независимы: чтобы скрывать child целиком, дополнительно задайте
безопасную `condition`.

### Несколько входных полей

Когда options зависят от двух и более полей, не передавайте handler всю форму.
Объявите минимальный allowlist:

```python
from forms.fields import ReferenceDependency

FieldDefinition(
    key="methods",
    label="Методы",
    field_type=FieldType.MULTISELECT,
    reference=ReferenceConfig(
        source="corp_swagger",
        resource="swagger_methods",
        value_key="id",
        label_key="name",
        required_params=("api_id", "source"),
    ),
    reference_dependencies=(
        ReferenceDependency("api", parameter="api_id", item_field="id"),
        ReferenceDependency("source"),
        ReferenceDependency("swagger_file", parameter="document"),
    ),
)
```

Runtime нормализует значения и передаёт в `extra_params` только эти поля.
`FILE` передаётся как содержимое, `SELECT` — как сохранённый `value_key`, а
`item_field` явно запрашивает атрибут полного выбранного item. Все зависимости
по умолчанию должны быть sibling fields (`scope="current"`). Для справочника
внутри `ServerActionDialog` разрешено обратиться к корневому полю основной
формы через явный `scope="form"`:

```python
ReferenceDependency(
    "swagger_file",
    parameter="document",
    scope="form",
)
```

Полный сценарий action dialog со Swagger находится в
[ACTION_DIALOGS.md](ACTION_DIALOGS.md).

## Cache

Factory получает public persistent `ReferenceCache`. Corporate handler сам
решает, использовать ли его. Cache key должен различать как минимум:

```text
resource + environment + отсортированные dependency params
```

Иначе методы API A могут попасть в форму API B. Не включайте bearer/PAT или
персональные данные в cache key/filename. Для refresh UI public runtime вызывает
`cache.invalidate(resource, environment)`; если corporate handler использует
второй cache, он должен согласовать с этим действием его invalidation либо не
обещать поддержку refresh.

Этот же shared cache обслуживает быстрые `@`-ссылки в AI-чате. Поиск упоминаний
использует ровно API/application `ReferenceConfig`, возвращённые
`AUTODEPLOY_SEARCH_CATALOG_FACTORY`, и проверяет только объявленные
`search_keys`. Справочники отдельных полей форм и плагинов сюда не добавляются:
это исключает дубли одного API по всем формам, где он встречается. Lookup
принципиально не вызывает handler, resolver, HTTP endpoint или refresh:
просроченный snapshot разрешён, а при отсутствии cache результат просто пуст.
Поэтому corporate handler search-каталога обязан сохранять успешный ответ именно
в переданный factory экземпляр `ReferenceCache` с корректными `resource` и
`environment`.
Перед отправкой в модель выбранный browser pointer повторно разрешается по
текущему snapshot; доверять присланным browser label/полям нельзя.

## Глобальный поиск API и приложений

Страница поиска не использует захардкоженные public dictionaries, если настроена
corporate factory:

```python
from forms.fields import ReferenceConfig


def create_search_catalogs(env_manager):
    return {
        "api": ReferenceConfig(
            source="corp_http",
            resource="gravitee_apis",
            value_key="id",
            label_key="name",
            search_keys=("context_path", "name", "id"),
            detail_keys=("id", "name", "context_path", "owner"),
        ),
        "application": ReferenceConfig(
            source="corp_http",
            resource="gravitee_applications",
            value_key="id",
            label_key="name",
            search_keys=("azp", "name", "id"),
            detail_keys=("id", "name", "azp"),
        ),
    }
```

Factory обязана вернуть ровно `api` и `application`; у каждой записи обязательны
`source`, `resource` и непустые `search_keys`. Поиск выполняется Python runtime
по выбранным пользователем environment combinations (`TEST/REGRESS/PROD` и
`INT/EXT`), начинается после 200 ms debounce и никогда не отправляет справочник
в браузер целиком.

```dotenv
AUTODEPLOY_SEARCH_CATALOG_FACTORY=corp_autodeploy.search_catalogs:create_search_catalogs
```

Кнопка refresh сначала показывает timestamp текущего cache по каждому selected
environment и запрашивает подтверждение. Result cards используют тот же
read-only detail contract.

## Связь с AI

Reference values не загружаются в main Copilot и form-search session. После
выбора конкретной формы Copilot видит field type и либо small inline options,
либо вызывает узкий `search_reference_options`. Python преобразует semantic
label в `value_key` и повторно валидирует draft. Поиск значений формы не должен
выполняться через JSON Repository MCP, если authoritative form reference уже
содержит нужный вариант.

Оператор может явно приложить cached reference к сообщению через `@`. В prompt
попадает authoritative `value_key`, короткая подпись и ограниченный набор
описательных полей как недоверенные данные. Copilot не должен повторно искать
объект только ради определения, что имел в виду оператор; если для операции
нужна более свежая или отсутствующая характеристика объекта, он по-прежнему
может запросить её узким инструментом.

## Тесты

Проверьте для каждого resource:

- `supports()` принимает только private source;
- response mapping и пропуск malformed items;
- auth/environment routing;
- SELECT scalar и MULTISELECT list;
- поиск по каждому `search_key` и порядок отображения;
- выбранный item остаётся первым при filter/paging и после загрузки draft;
- dependency params, empty parent и смена parent;
- cache isolation, TTL/refresh и concurrent load;
- detail response не содержит private/secret fields;
- ожидаемая network error возвращает пустой безопасный result и оставляет
  полезный server log.
