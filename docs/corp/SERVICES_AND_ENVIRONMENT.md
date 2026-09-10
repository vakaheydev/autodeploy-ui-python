# Сервисы, авторизация и окружения

## RuntimeServices

Public core не содержит реальных ITSM/TFS/Gravitee endpoint. Private factory
возвращает три объекта, которые runtime инжектирует в каждую request-scoped
копию формы:

```python
from webapp.extensions import RuntimeServices


class CorporateITSM:
    def __init__(self, env_manager, http_client):
        self.env = env_manager
        self.http = http_client

    def get_ticket(self, ticket_id: str, environment: str = ""):
        # Вернуть dict/list с корпоративными данными.
        ...

    def get_ai_prompt(self, request):
        # Опционально: выбрать статические AI-инструкции по типу заявки.
        # Полный typed пример — в ITSM_FORM_FILLING.md.
        return None


class CorporateTFS:
    def __init__(self, env_manager, http_client):
        self.env = env_manager
        self.http = http_client

    def get_pull_request(self, reference, environment: str = ""):
        ...


class CorporateGravitee:
    def __init__(self, env_manager, http_client):
        self.env = env_manager
        self.http = http_client

    # Здесь находятся методы, вызываемые private forms/actions.


def create_services(env_manager, http_client):
    return RuntimeServices(
        itsm=CorporateITSM(env_manager, http_client),
        tfs=CorporateTFS(env_manager, http_client),
        gravitee=CorporateGravitee(env_manager, http_client),
    )
```

Подключение:

```dotenv
AUTODEPLOY_SERVICE_PROVIDER=corp_autodeploy.services:create_services
```

Форма получает объекты как `self.itsm_service`, `self.tfs_service` и
`self.gravitee_service`. Плагин получает тот же результат provider через
`PluginContext.services`, а раздел заявок — через `TicketContext.services`.
Private provider также может вернуть собственный
typed container с дополнительными сервисами, например `analytics`. Конкретные
дополнительные методы являются private contract между формами/плагинами и
adapters и должны тестироваться внутри одного package. Полный contract custom
pages описан в [PLUGINS.md](PLUGINS.md).
Контракт списка/карточки ITSM описан в [TICKETS.md](TICKETS.md).

Factory может создавать lightweight clients на запрос. Connection pool или
shared cache разрешён только при thread-safe реализации; mutable auth state
нельзя разделять между одновременными requests разных environments.

## HTTP client

Public `core.http_client.HttpClient` основан на `urllib`, умеет GET/POST/PUT/
DELETE, JSON, Bearer и Basic auth, timeout, response-size limit и safe URL logs.
Container передаёт client без redirect и с лимитом ответа 10 MiB.

Private adapters могут использовать его либо свою корпоративную библиотеку.
Если используется `requests==2.32.3`, зависимость объявляется только в private
`pyproject.toml`, а её wheel включается в offline release. Не добавляйте её в
public core ради одного corporate adapter.

Обязательные свойства любого adapter:

- explicit timeout на каждый request;
- TLS verification и corporate certificate configuration;
- bounded response read;
- отсутствие token/query secrets в log URL;
- controlled redirect policy: не переносить `Authorization` на другой host;
- преобразование transport/vendor errors в безопасное domain exception;
- никакого глобального auth state между environments.

## Submit auth

Форма выбирает auth через `get_auth_type()`; public `SubmitService` применяет:

| Значение | Wire format | `.env` source |
|---|---|---|
| `gravitee` | `Authorization: Bearer <token>` | `GRAVITEE_TOKEN_<ENV>` |
| `tfs` | `Authorization: Basic base64(:<PAT>)` | `TFS_TOKEN`; username всегда пустой |
| `itsm` | `Authorization: Basic base64(<login>:<password>)` | `ITSM_LOGIN`, `ITSM_PASSWORD` |
| `none` | без Authorization | — |

Пример TFS-формы:

```python
def get_auth_type(self) -> str:
    return "tfs"
```

Не добавляйте Authorization через `get_submit_headers()`: это создаёт два
источника истины. Для нестандартного private auth используйте server-side
adapter/endpoint либо сначала добавьте явный public contract.

`pre_submit()` вызывается после выбора auth и `build_payload()`, перед отправкой.
Он может изменить payload in place или выбросить ошибку. Токен не нужно и нельзя
добавлять в payload.

## Окружение в формах и сервисах

Authoritative keys объявлены public core и передаются строкой, например
`test_int`, `test_ext`, `regress_int`, `prod_ext`.

- form endpoint/action/service method всегда принимает `environment` явно;
- в `validate()` доступна request-scoped строка `self.current_environment`;
- `self.screen.app.current_environment.get()` в web не поддерживается;
- service не должен угадывать environment из глобальной переменной;
- plugin operation/render получает тот же key как `context.environment`;
- endpoint/token maps должны отклонять неизвестный key, а не fallback на prod.

## Hook переключения окружения

Browser сначала вызывает `POST /api/v1/environments/activate`. Только после
успешного ответа он фиксирует selection и перезагружает form/reference state.

Private factory:

```python
from webapp.extensions import EnvironmentChangeRejected


class CorporateEnvironmentError(Exception):
    pass


def create_environment_hook(env_manager):
    def activate(
        previous_environment: str | None,
        environment: str,
    ) -> None:
        try:
            # check_connectivity(environment)
            # refresh_small_read_only_snapshot(environment)
            pass
        except CorporateEnvironmentError as exc:
            raise EnvironmentChangeRejected(
                f"Не удалось подготовить окружение {environment}"
            ) from exc

    return activate
```

```dotenv
AUTODEPLOY_ENVIRONMENT_HOOK=corp_autodeploy.environment:create_environment_hook
```

Точная сигнатура hook:

```text
hook(previous_environment: str | None, environment: str) -> None
```

- factory создаётся один раз при startup;
- hook вызывается только при реальном изменении environment;
- вызовы сериализованы server lock;
- normal return разрешает переключение;
- `EnvironmentChangeRejected(message)` возвращает safe HTTP 422 рядом с
  environment picker;
- текст любого другого exception скрывается от браузера, traceback остаётся в
  server log;
- при отказе frontend сохраняет прежнее окружение.

Hook должен быть быстрым и идемпотентным. Он подходит для проверки доступности,
переключения legacy context или атомарного refresh небольшого snapshot. Формы и
services всё равно обязаны принимать explicit environment. Долгий полный sync
лучше вынести в отдельный action/cache refresh.

## ITSM/ADO context и очистка

Основной minimum protocol для AI context:

```text
itsm.get_ticket(ticket_id, environment="") -> JSON-compatible value
tfs.get_pull_request(reference, environment="") -> JSON-compatible value
```

Опциональный typed capability ITSM-service:

```text
itsm.get_ai_prompt(ITSMAIPromptRequest) -> ITSMAIPrompt | None
```

Он определяет стабильный корпоративный тип заявки и может вернуть проверенные
fallback-инструкции. Оператор может переопределить prompt для возвращённого
типа через **Настройки → ITSM и AI**; для этого adapter вправе вернуть пустые
`instructions`, но обязан вернуть `ticket_type`. Capability обслуживает и
главный Copilot, и exact-form AI fill; старым adapters добавлять его не
обязательно. Полный контракт, trust boundary и порядок приоритетов приведены в
[ITSM_FORM_FILLING.md](ITSM_FORM_FILLING.md#инструкции-по-типу-заявки).

Полученные данные считаются недоверенными. До передачи AI нужно оставить только
необходимые поля, ограничить размер и удалить secrets/confidential content.
Корпоративный service может возвращать богатый внутренний object для формы, но
слой AI context должен строить отдельное безопасное представление. Никогда не
передавайте raw headers, cookies, tokens, password fields и полный ответ ITSM.

## Errors и logging

Логируйте operation, service, environment, HTTP status, duration и request ID.
Не логируйте Authorization, `.env`, raw confidential body, полный ticket/PR и
query с secrets. Пользовательская ошибка должна объяснять, что можно исправить;
server log — сохранять exception type/traceback для диагностики.

Стандартные server logs:

- Windows: `%LOCALAPPDATA%\GraviteeAutoDeploy\logs\autodeploy.log`;
- Linux: `~/.local/share/gravitee-autodeploy/logs/autodeploy.log`;
- override: process variable `AUTODEPLOY_LOG_DIR`.

## Contract tests

Покройте:

- factory возвращает три usable service object;
- plugin context получает результат того же provider и выбранное environment;
- ticket/PR happy path, timeout, 4xx/5xx, malformed/oversized response;
- AI prompt hook: известный/неизвестный тип, main-chat/exact-form context,
  неверный return type и redaction;
- endpoint/auth selection для каждого environment;
- TFS Basic header декодируется в пустой username + PAT;
- parallel requests разных environments не смешивают auth;
- hook success, repeated same-environment no-op, safe rejection и unexpected
  exception redaction;
- пользовательская error не содержит secret, raw response или internal URL;
- server log содержит достаточный request correlation без credentials.
