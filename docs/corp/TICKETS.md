# Раздел «Заявки»

Раздел `/tickets` — generic React-интерфейс над корпоративным Python-провайдером.
Публичное ядро не знает URL, формат ответа или правила ITSM. Оно отвечает только
за HTTP-контракт, отображение, проверку безопасного UI-документа, подтверждение
действий и обработку конкурентного изменения карточки.

Корпоративный пакет отвечает за всё содержимое:

- какие заявки считаются текущими;
- по каким полям искать, фильтровать и сортировать;
- как выглядит строка списка и полная карточка;
- какие кнопки доступны, как они называются и окрашиваются;
- какой Python-метод выполняется по каждой кнопке;
- какие credentials, endpoint и domain rules применяются.

Не добавляйте отдельный corporate React-компонент и не возвращайте браузеру
callable, endpoint или credentials.

## Подключение

Добавьте модуль `src/corp_autodeploy/tickets.py` и настройку:

```dotenv
AUTODEPLOY_TICKET_PROVIDER=corp_autodeploy.tickets:create_ticket_provider
```

Factory вызывается один раз при старте:

```python
def create_ticket_provider(env_manager):
    return CorporateTicketProvider()
```

После изменения import path нужен полный restart Python server. Если настройка
пуста, пункт меню остаётся доступным, но показывает безопасное состояние
«Раздел заявок не подключён» и не делает корпоративных сетевых запросов.

## Обязательный интерфейс

Provider реализует четыре метода:

```python
from tickets import (
    TicketCard,
    TicketContext,
    TicketListConfiguration,
    TicketListRequest,
    TicketPage,
)


class CorporateTicketProvider:
    def get_list_configuration(
        self, context: TicketContext,
    ) -> TicketListConfiguration:
        ...

    def load_current_tickets(
        self, context: TicketContext, request: TicketListRequest,
    ) -> TicketPage:
        ...

    def find_tickets(
        self, context: TicketContext, request: TicketListRequest,
    ) -> TicketPage:
        ...

    def load_ticket_card_by_id(
        self, context: TicketContext, ticket_id: str,
    ) -> TicketCard:
        ...
```

`load_ticket_card_by_id` — правильное имя метода; `by_jd` не используется.

`TicketContext` создаётся заново на запрос и содержит:

- `environment`: активный ключ окружения, например `test_int`;
- `env_manager`: server-side доступ к whitelisted/private `.env` values;
- `http_client`: настроенный public HTTP client;
- `services`: результат `AUTODEPLOY_SERVICE_PROVIDER`, обычно с
  `services.itsm`, `services.tfs` и `services.gravitee`.

Provider не должен сохранять `TicketContext` или token в singleton state.

## Точная последовательность вызовов

```text
Открытие /tickets
  -> get_list_configuration(context)
  -> load_current_tickets(context, request)

Введён непустой поисковый запрос
  -> find_tickets(context, request)

Поиск очищен
  -> load_current_tickets(context, request)

Открыта строка списка
  -> load_ticket_card_by_id(context, ticket_id)

Нажата corporate-кнопка
  -> load_ticket_card_by_id(...) для актуальной версии/actions
  -> optional одноразовое подтверждение public core
  -> TicketAction.handler(context, ticket_id)
  -> load_ticket_card_by_id(...) ещё раз, если reload_card=True
```

Фильтры и сортировки не выполняются во frontend. Browser лишь возвращает
выбранные значения; private provider применяет их к своему ITSM-запросу.

## Фильтры, сортировки и пагинация

`get_list_configuration()` описывает generic toolbar:

```python
from tickets import (
    TicketFilterDefinition,
    TicketFilterOption,
    TicketListConfiguration,
    TicketSortDefinition,
)


def get_list_configuration(self, context):
    return TicketListConfiguration(
        description="Назначенные пользователю заявки",
        filters=(
            TicketFilterDefinition(
                key="status",
                label="Статус",
                kind="select",
                placeholder="Все статусы",
                options=(
                    TicketFilterOption("active", "Активные"),
                    TicketFilterOption("done", "Завершённые"),
                ),
            ),
            TicketFilterDefinition(
                key="ticket_types",
                label="Тип заявки",
                kind="multiselect",
                options=(
                    TicketFilterOption("api", "API"),
                    TicketFilterOption("application", "Приложение"),
                ),
            ),
            TicketFilterDefinition(
                key="created_from",
                label="Создана после",
                kind="date",
            ),
        ),
        sorts=(
            TicketSortDefinition("updated", "По обновлению"),
            TicketSortDefinition("created", "По созданию"),
            TicketSortDefinition("priority", "По приоритету"),
        ),
        default_sort="updated",
        default_direction="desc",
        page_size=25,
    )
```

Поддерживаемые `kind`: `text`, `select`, `multiselect`, `date`, `boolean`.
Для `select`/`multiselect` задайте конечный список `options`; неизвестное
значение public runtime отклонит до вызова ITSM.

`TicketListRequest` уже нормализован:

```python
TicketListRequest(
    environment="test_int",
    query="REQ-42",
    filters={"status": "active", "ticket_types": ["api"]},
    sort_key="updated",
    sort_direction="desc",
    offset=0,
    limit=25,
)
```

Private метод обязан применить `filters`, `sort_key`, `sort_direction`,
`offset` и `limit`. Возвращайте не больше `request.limit` элементов, а `total`
должен означать полное число совпадений после поиска/фильтров, до пагинации.

## Строка списка и карточка

Преобразуйте private ITSM DTO в public view models. Не возвращайте raw response:

```python
from tickets import (
    TicketAttribute,
    TicketCard,
    TicketListItem,
    TicketPage,
    TicketSection,
)


def _list_item(raw) -> TicketListItem:
    return TicketListItem(
        ticket_id=raw.number,
        title=raw.title,
        subtitle=raw.service_name,
        status=raw.status_label,
        status_tone="info",
        updated_at=raw.updated_at.isoformat(),
        attributes=(
            TicketAttribute("priority", "Приоритет", raw.priority),
            TicketAttribute("assignee", "Исполнитель", raw.assignee),
        ),
    )


def load_current_tickets(self, context, request):
    page = context.services.itsm.load_current_tickets(request)
    return TicketPage(
        items=tuple(_list_item(item) for item in page.items),
        total=page.total,
    )


def find_tickets(self, context, request):
    page = context.services.itsm.find_tickets(request)
    return TicketPage(
        items=tuple(_list_item(item) for item in page.items),
        total=page.total,
    )
```

Имена методов private ITSM adapter внутри примера не являются public contract:
их определяет корпоративный пакет. Public contract начинается с методов
`CorporateTicketProvider`.

Полная карточка группирует данные в секции:

```python
def load_ticket_card_by_id(self, context, ticket_id):
    raw = context.services.itsm.get_ticket(ticket_id)
    if raw is None:
        raise TicketNotFound(ticket_id)
    return TicketCard(
        ticket_id=raw.number,
        title=raw.title,
        subtitle=raw.service_name,
        description=raw.description,
        status=raw.status_label,
        status_tone="info",
        updated_at=raw.updated_at.isoformat(),
        sections=(
            TicketSection("main", "Основное", (
                TicketAttribute("author", "Автор", raw.author, copyable=True),
                TicketAttribute("created", "Создана", raw.created_at.isoformat(), kind="datetime"),
            )),
            TicketSection("details", "Детали", (
                TicketAttribute("request", "Текст заявки", raw.description, kind="multiline"),
                TicketAttribute("payload", "Технические данные", raw.safe_metadata, kind="json"),
            )),
        ),
        actions=self._actions(raw),
    )
```

`TicketAttribute.kind`: `text`, `multiline`, `code`, `datetime`, `badge`,
`json`. `tone`: `default`, `info`, `success`, `warning`, `danger`. Для ссылки
задайте `url` (same-origin либо HTTP(S)); `copyable=True` включает копирование.

## Кнопки и корпоративные методы

Кнопка является `TicketAction`, возвращённым именно для текущей карточки. Таким
образом private provider полностью определяет текст, доступность, порядок, цвет
и обработчик:

```python
from tickets import TicketAction, TicketActionResult, TicketUserError


class CorporateTicketProvider:
    def _actions(self, raw):
        actions = []
        if raw.can_take:
            actions.append(TicketAction(
                action_id="take",
                label="Взять в работу",
                description="Назначить текущего пользователя исполнителем",
                style="success",
                color="#147D64",        # optional exact RGB override
                confirmation_text="Взять заявку в работу?",
                handler=self._take,
            ))
        actions.append(TicketAction(
            action_id="complete",
            label="Завершить",
            style="primary",
            confirmation_text="Завершить заявку?",
            disabled_reason="Сначала заполните результат" if not raw.can_complete else "",
            handler=self._complete,
        ))
        return tuple(actions)

    def _take(self, context, ticket_id):
        context.services.itsm.take_ticket(ticket_id)
        return TicketActionResult("Заявка назначена вам")

    def _complete(self, context, ticket_id):
        try:
            context.services.itsm.complete_ticket(ticket_id)
        except SomeCorporateDomainError as exc:
            raise TicketUserError("ITSM не разрешает завершить эту заявку") from exc
        return TicketActionResult("Заявка завершена", reload_card=True)
```

Поддерживаемые `style`: `primary`, `secondary`, `success`, `warning`, `danger`.
`color` необязателен и принимает только `#RGB`/`#RRGGBB`. Предпочитайте
семантический `style`; custom color нужен для корпоративно узнаваемого действия.

Правила:

- `action_id` стабилен, уникален в карточке и не зависит от подписи;
- side effect существует только в `handler(context, ticket_id)`;
- destructive action всегда задаёт `confirmation_text`;
- `disabled_reason` одновременно блокирует кнопку и объясняет причину;
- `handler` не сериализуется и никогда не попадает в браузер;
- после успеха карточка по умолчанию загружается заново;
- `reload_card=False` допустим только когда отображаемое состояние точно не
  изменилось;
- `TicketActionResult.data` должен содержать только безопасный JSON и обычно не
  нужен UI.

Public runtime перед выполнением снова загружает карточку и сверяет её version.
Если набор/состояние actions устарели, browser получает HTTP 409 и должен
обновить карточку. Confirmation token короткоживущий, одноразовый и привязан к
ticket/action/environment/version.

## Ошибки

- `TicketNotFound` → HTTP 404;
- `TicketUserError("безопасный текст")` → HTTP 422 с текстом для оператора;
- устаревшая карточка → HTTP 409;
- нарушение public view-model contract → HTTP 502, детали только в server log;
- необработанная ошибка integration → HTTP 502, traceback только в server log.

Не помещайте в `TicketUserError` raw response, Authorization, token, password,
cookie, персональные данные сверх того, что пользователь и так видит в карточке,
или private URL с credentials.

## REST API

Frontend использует:

- `GET /api/v1/tickets/configuration?environment=...`;
- `POST /api/v1/tickets/query`;
- `POST /api/v1/tickets/card`;
- `POST /api/v1/tickets/actions/{action_id}`.

Карточка загружается через POST, чтобы arbitrary corporate ticket ID не попадал
в URL path. API является transport boundary; внешним клиентам нельзя вызывать
private service напрямую.

## Минимальные contract tests private-пакета

Проверьте как минимум:

1. `load_current_tickets` с default filter/sort и пагинацией;
2. `find_tickets` с query + всеми комбинациями фильтров;
3. пустую страницу и корректный `total`;
4. существующую и отсутствующую карточку;
5. видимые/disabled actions для разных статусов;
6. каждый handler: success, safe domain error и network error;
7. destructive confirmation через public API;
8. смену окружения: методы получают новый `context.environment` и не переиспользуют
   идентификаторы другого контура;
9. отсутствие secrets/raw confidential fields в list/card/error/log;
10. установку private wheel рядом с зафиксированной версией public wheel.

Отдельно выполните browser smoke: открыть `/tickets`, применить фильтр, найти
заявку, открыть карточку, отменить confirmation и затем успешно выполнить одну
тестовую кнопку.
