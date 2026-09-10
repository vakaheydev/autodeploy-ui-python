# Заполнение формы из ITSM

## Контракт

Кнопка «Подтянуть заявку» вызывает Python-hook выбранной формы:

```python
fetch_from_itsm(environment: str, ticket_id: str)
```

Форма сама выбирает способ обработки, возвращая один из двух вариантов
`ITSMFetchResult`:

```python
from forms.base_form import ITSMFetchResult
```

- `ITSMFetchResult.deterministic(values)` — корпоративный Python-код уже знает
  точные значения полей;
- `ITSMFetchResult.ai(context, instruction=...)` — корпоративный код подготавливает
  JSON-контекст, а основной Copilot сопоставляет его с полями этой формы.

Это решение принимается внутри `fetch_from_itsm`. Отдельная настройка режима на
фронтенде не нужна.

## Режим deterministic

Используйте его, когда заявка имеет стабильную структуру и преобразование не
требует интерпретации:

```python
from forms.base_form import BaseForm, ITSMFetchResult


class CreateAPIForm(BaseForm):
    @property
    def itsm_support(self) -> bool:
        return True

    def fetch_from_itsm(self, environment: str, ticket_id: str):
        ticket = self.itsm_service.get_ticket(ticket_id, environment)
        return ITSMFetchResult.deterministic({
            "name": ticket["service_name"],
            "description": ticket.get("summary", ""),
            "context_path": ticket["context_path"],
        })
```

Сервер объединяет patch с уже введёнными пользователем значениями, заново
вычисляет conditional fields, нормализует типы и выполняет Python validation.
Только после успешного ответа React обновляет форму. Неизвестные keys
игнорируются по legacy-правилам `apply_form_data`.

До обновления корпоративных форм допустим прежний return обычного `dict` или
`None`: runtime трактует его как deterministic-режим. Для нового кода используйте
явный `ITSMFetchResult`.

## Режим AI

Используйте его, когда смысл полей зависит от текста заявки, PR или нескольких
корпоративных источников:

```python
from forms.base_form import BaseForm, ITSMFetchResult


class CreateAPIForm(BaseForm):
    @property
    def itsm_support(self) -> bool:
        return True

    def fetch_from_itsm(self, environment: str, ticket_id: str):
        ticket = self.itsm_service.get_ticket(ticket_id, environment)
        pull_request = self.tfs_service.get_pull_request(
            ticket.get("pull_request_id"),
            environment,
        )
        return ITSMFetchResult.ai(
            context={
                "ticket": self._ticket_context(ticket),
                "pull_request": self._pull_request_context(pull_request),
            },
            instruction=(
                "При конфликте заявки и PR не угадывай значение; оставь поле "
                "для ручного решения."
            ),
        )
```

`context` обязан быть JSON-объектом (`dict`/`Mapping`). Включайте только данные,
нужные для этой формы. Не передавайте raw HTTP response, headers, cookies,
credentials, полную историю заявки или unrelated attachments. Public runtime
дополнительно выполняет redaction и ограничение коллекций, но это страховка, а
не замена корпоративной выборке.

`instruction` необязателен. Он уточняет только правила сопоставления конкретной
формы; endpoint, credentials, вызовы write API и секреты туда не помещаются.

## Инструкции по типу заявки

Общие корпоративные правила не нужно дублировать во всех формах. ITSM-service
может реализовать опциональный публичный capability `get_ai_prompt`. Он получает
уже очищенный контекст, определяет корпоративный тип заявки и возвращает
типизированный результат:

```python
from opencode_integration import ITSMAIPrompt, ITSMAIPromptRequest


PROMPTS_BY_TYPE = {
    "create_api_v2": """
        Поле service_name является предлагаемым названием API.
        contextPath брать только из секции requested_api.
        Если owner отсутствует, оставь значение неподтверждённым.
    """.strip(),
    "enable_ingress": """
        requested_ingresses сопоставляй с полным inline-справочником формы.
        Не ищи типы ingress в JSON Repository.
    """.strip(),
}


class CorporateITSM:
    def get_ticket(self, ticket_id: str, environment: str = ""):
        ...

    def get_ai_prompt(
        self,
        request: ITSMAIPromptRequest,
    ) -> ITSMAIPrompt | None:
        # В main chat request.form_id == "". При заполнении уже открытой
        # формы здесь находится её стабильный form_id.
        ticket_type = str(
            request.ticket_context.get("request_type", "")
        ).strip()
        instructions = PROMPTS_BY_TYPE.get(ticket_type)
        if instructions is None:
            return None
        return ITSMAIPrompt(
            ticket_type=ticket_type,
            instructions=instructions,
        )
```

Поля `ITSMAIPromptRequest`:

| Поле | Значение |
|---|---|
| `ticket_id` | нормализованный номер заявки |
| `environment` | выбранный key окружения, например `test_int` |
| `ticket_context` | уже secret-redacted JSON-контекст заявки |
| `form_id` | пусто при выборе формы главным Copilot; exact ID при `fetch_from_itsm` |

`get_ai_prompt` — опциональная возможность, а не новый обязательный метод
`ITSMDataSource`. Старые adapters только с `get_ticket` продолжают работать.
Public `ITSMService` также содержит no-op реализацию, возвращающую `None`.

Результат добавляется в отдельный `TRUSTED_ITSM_AI_PROMPT`:

- при первом прикреплении заявки в главный Copilot;
- при добавлении новой заявки в уже живую chat session;
- в legacy router и form extractor;
- при AI-режиме `fetch_from_itsm` конкретной формы.

В последнем сценарии hook получает именно очищенный `context`, который форма
вернула через `ITSMFetchResult.ai`. Поэтому включите туда стабильный ключ типа
заявки. Runtime объединяет общую инструкцию service с дополнительным
`ITSMFetchResult.ai(..., instruction=...)`: сначала общая политика типа, затем
правило конкретной формы.

### Граница доверия

`instructions` считается доверенной корпоративной конфигурацией. Возвращайте
только заранее проверенный статический текст из mapping по типу. Никогда не
вставляйте туда `description`, комментарии, ответы пользователя или иной raw
текст заявки через f-string: тогда недоверенные данные ошибочно станут частью
доверенного prompt. Факты заявки уже передаются отдельно и остаются внутри
`BEGIN_UNTRUSTED_*` / `END_UNTRUSTED_*`.

Инструкции не могут разрешить новые tools, submit/deploy, обход Python validation
или human confirmation. Public core удаляет похожие на секреты присваивания,
ограничивает `ticket_type` 200 символами и суммарные инструкции 16 000
символами. Неверный return type или exception hook останавливает именно
ITSM→AI операцию с безопасной ошибкой; traceback остаётся в server log.

Сервер выполняет AI-режим так:

```text
fetch_from_itsm -> sanitized JSON context
                -> новая основная Copilot session
                -> persistent pending draft точной формы и environment
                -> get_form_schema + reference tools при необходимости
                -> prepare_form_draft с тем же draft_id
                -> значения прямо в форме + approve/reject каждого поля
                -> обычный preview/submit только после решения пользователя
```

Copilot не запускает семантический поиск формы: `form_id`, `environment`, версия
и `draft_id` уже зафиксированы сервером. Он также не загружает заявку повторно
через generic ITSM data source. Если Copilot не подготовил draft, форма остаётся
без частичных изменений, а причина появляется в состоянии черновика.

Для AI-режима нужны:

- подключённый OpenCode Server;
- доступная модель в `opencode.json`;
- `AUTODEPLOY_MCP_ENABLED=true` и доступный AutoDeploy MCP;
- разрешённый инструмент `prepare_form_draft` из стандартного профиля Copilot.

При отсутствии этих условий endpoint возвращает понятную операционную ошибку,
которая отображается прямо в диалоге заявки.

## Смешанный выбор в одной форме

Режим можно выбирать по типу или полноте конкретной заявки:

```python
def fetch_from_itsm(self, environment: str, ticket_id: str):
    ticket = self.itsm_service.get_ticket(ticket_id, environment)
    if ticket.get("template") == "create_api_v2" and ticket.get("context_path"):
        return ITSMFetchResult.deterministic(self._exact_values(ticket))
    return ITSMFetchResult.ai(
        self._ai_context(ticket),
        instruction="Заполни только значения, подтверждённые заявкой.",
    )
```

Не вызывайте `self.apply_form_data()` в AI-режиме: исходные факты должны быть в
`context`. В deterministic-режиме `self.apply_form_data()` всё ещё поддержан для
совместимости, но явный `values` проще тестировать.

## Минимальные тесты корпоративной формы

Покройте отдельно:

1. deterministic-заявку и точный patch;
2. AI-заявку, состав и размер context, отсутствие секретов;
3. выбор режима для каждого поддержанного типа заявки;
4. `get_ai_prompt` для известного и неизвестного типа, а также `form_id=""` и
   exact-form вызов;
5. отсутствие raw ticket text/secrets в `instructions`;
6. исключение ITSM/TFS/prompt hook без частичного изменения формы;
7. сохранение уже введённых значений, если patch их не меняет;
8. AI draft в том же `form_id` и environment;
9. conditional, SELECT, MULTISELECT и повторяемые BLOCK после применения.

Сам `fetch_from_itsm` тестируйте как обычный Python-метод с fake корпоративными
services. Отдельным integration-тестом вызовите `POST
/api/v1/forms/{form_id}/ticket` и проверьте `mode` в ответе.
