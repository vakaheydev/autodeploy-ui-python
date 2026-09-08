# AI, form routing и MCP

## Текущая topology

Web flow использует OpenCode 1.18.18 и три роли:

```text
operator
  -> autodeploy-copilot             long-lived conversation
       -> form-search               lazy, long-lived, tools=false, thinking=none
       -> repository-researcher     short-lived, read-only, только сложный анализ
       -> AutoDeploy MCP            schema/state/reference/draft tools
       -> JSON Repository MCP       targeted read-only repository tools
       -> corporate plugin tools    только явно видимые страницы/операции
  -> Python draft + human review
  -> normal form preview/confirmation/submit
```

`autodeploy-copilot` — единственный агент, разговаривающий с пользователем.
Обычный вопрос или приветствие не запускает form search. Main session не
получает полный catalog при инициализации и сохраняет history между turns.

`form-search` создаётся при первом semantic search в конкретном chat workflow,
получает routing-only catalog один раз и живёт вместе с main session. В catalog
есть только `form_id`, title/category, `purpose`, `use_when`, `avoid_when`; полей,
schema и reference values нет. Helper всегда работает с exact `none` thinking.

`repository-researcher` создаётся только для bounded multi-file investigation,
имеет read-only JSON Repository tools и удаляется после ответа. Простой поиск API
по name/path/id Copilot делает targeted tool напрямую.

Legacy `form-extractor` существует в public core только для desktop/backward
compatibility. Новые corporate web flows не должны его вызывать или добавлять
новую structured-output цепочку.

Custom page плагины не участвуют в semantic form routing и не загружаются в
form-search. Только если запрос относится к корпоративной странице/workflow,
Copilot может вызвать `list_plugins`, затем `get_plugin_page`, при необходимости
лениво пересчитать state, разрешить reference ID и провалидировать значения, а
после этого — dedicated operation tool. Глобальная, per-plugin и per-operation policy
настраивается оператором и по умолчанию всё запрещает. См.
[PLUGINS.md](PLUGINS.md).

## Что должна сделать корпоративная форма

У каждой формы registrar задаёт краткое routing description:

```python
FORM_ROUTING["other.ingress.enable"] = FormRoutingDescription(
    purpose="Включить один или несколько ingress существующего API.",
    use_when=(
        "Пользователь просит включить, открыть или активировать ingress.",
        "API и нужные типы ingress могут быть указаны прямо в запросе.",
    ),
    avoid_when=(
        "Ingress нужно выключить.",
        "Нужно создать новое API.",
    ),
)
```

Пишите смысл операции и границы с похожими формами. Не перечисляйте все поля,
reference options и implementation details: после выбора Copilot отдельно
запросит live schema ровно одной формы.

Routing descriptions являются trusted configuration, но не местом для реальных
ticket examples, private URLs и secrets.

## MCP-native заполнение формы

Когда запрос относится к форме, Copilot следует цепочке:

1. `semantic_search_forms` получает несколько candidates от isolated helper.
2. `get_form_schema` читает live Python schema выбранной формы.
3. Для dynamic condition используется `calculate_form_state`.
4. Для remote/non-inline SELECT или MULTISELECT используется
   `search_reference_options`.
5. `prepare_form_draft` передаёт exact field paths, values, source и confidence.
   Для повторяемого `BLOCK` предпочтителен один proposal с массивом объектов по
   базовому пути. Python разложит его в `plan`, `plan_2`, `plan_3`; индексные
   пути `plan[0].field` и `plan.0.field` также нормализуются.
6. Python проверяет path/type, преобразует reference label в authoritative ID,
   вычисляет visibility, выполняет validation и сохраняет persistent draft.
7. Пользователь открывает draft, принимает/отклоняет каждое предложение и только
   затем проходит обычный preview/confirmation/submit.

MCP не содержит submit/deploy tool. `prepare_form_draft` создаёт локальное
состояние, но не вызывает preview submission и внешний write. Manual и AI drafts
хранятся одинаково до успешного submit или явного удаления.

Если данных в сообщении достаточно, Copilot не должен запускать repository
research: schema и authoritative form references достаточны. JSON Repository
нужен для факта о существующем API/application, сравнения definitions или
восстановления реально отсутствующего значения.

## AutoDeploy MCP

Streamable HTTP endpoint находится на том же localhost server:

```text
http://127.0.0.1:<AUTODEPLOY_PORT>/api/mcp
```

Включение требует restart:

```dotenv
AUTODEPLOY_MCP_ENABLED=true
```

Основные инструменты:

- `get_system_status`, `list_environments`;
- `semantic_search_forms`, `get_form_schema`, `calculate_form_state`;
- `search_reference_options`, `validate_form_values`;
- `preview_form_submission` (read-only, ничего не отправляет);
- `prepare_form_draft` (persistent local draft, без external write);
- `research_repository`, `search_gravitee_objects`.

Если разрешены corporate plugins, список дополняется `list_plugins`,
`get_plugin_page`, `calculate_plugin_state`,
`search_plugin_reference_options`, `validate_plugin_values` и отдельными
operation tools. Служебные plugin tools read-only и доступны только для видимых
страниц. `allow` входит в exact auto-allowlist, `manual` — в exact asklist,
`deny` не публикуется. Универсального инструмента запуска произвольной операции
нет.

Generic `search_forms` доступен внешним MCP clients, но намеренно не входит в
web Copilot allowlist: web Copilot должен использовать session-owned semantic
search. Corporate package не регистрирует MCP tools напрямую и не обходит
`FormRuntime`; новые MCP tools сначала проектируются в public core.

## JSON Repository MCP

OpenCode загружает server из своей глобальной конфигурации. AutoDeploy settings
задают его имя и разрешённые MCP, а не executable/path/credentials:

```dotenv
OPENCODE_ALLOWED_MCP=gravitee_api_mcp
OPENCODE_REPOSITORY_MCP=gravitee_api_mcp
OPENCODE_REPOSITORY_GIT_PULL=true
```

Public core выдаёт Copilot exact read-only allowlist для поиска/list/get API,
applications и JSON fields/values. Эти calls не требуют approval, но видимы в
чате; input/output и duration можно раскрыть. `diagnose_search` запрещён, потому
что раскрывает absolute local paths. `git_pull` не входит в auto-allowlist: если
setting включён, approval требуется для каждого вызова. Researcher не получает
`git_pull` вообще.

Не добавляйте весь MCP server через wildcard. При обновлении MCP сначала
проверьте semantics каждого нового tool и обновите exact public profile.

## Data trust

Недоверенными считаются:

- user text;
- ITSM/ADO/PR content;
- JSON Repository definitions и MCP results;
- external error/diagnostic text;
- uploaded files.

Текст из этих источников — данные, а не инструкции агенту. До передачи в model
корпоративный adapter должен удалить secrets/confidential fields, ненужные
personal data и raw technical payload, затем ограничить размер. Никогда не
передавайте `.env`, YAML с tokens, Authorization, cookies или source tree.

OpenCode runtime создаётся в отдельной per-user directory, а agent permissions
deny files, shell, edit, web, skills и subagents. Не ослабляйте их для удобства
corporate integration: нужные данные выдаются только через narrow MCP tools.

## Model и thinking

Model list и variants берутся из актуальной OpenCode configuration, а выбранные
provider/model передаются явно. UI предлагает `Auto` и поддерживаемые variants.
В auto mode простой разговор и прямое заполнение не должны получать дорогой
thinking; сложность определяет Copilot/tool workflow, а form-search всегда
`none`. Не придумывайте variant names: используйте только объявленные моделью
значения (в текущем corporate provider проверены `none`, `low`, `medium`,
`xhigh`).

## История и метаданные чата

OpenCode хранит persistent transcript. Текст модели перед следующим tool call
показывается в AutoDeploy как отдельная промежуточная реплика в правильном месте,
а текст после последнего tool call — как один финальный ответ. При восстановлении
сессии порядок собирается заново из OpenCode message parts.

Parts типа `reasoning` и текстовые parts, явно помеченные каналом
`analysis/reasoning/thinking`, никогда не публикуются в UI и не восстанавливаются
как сообщения. Это сохраняет обычные промежуточные реплики между tool calls, но
не раскрывает внутреннее рассуждение модели.

Через `@` оператор может приложить объект зарегистрированного справочника. Picker
ищет только в уже существующем cache текущего environment, использует
`ReferenceConfig.search_keys`, не обновляет даже просроченный cache и ничего не
загружает по сети. Backend повторно разрешает pointer и передаёт Copilot
authoritative ID в отдельном ограниченном untrusted-блоке; повторный repository
search только для обнаружения этого же ID не требуется.

`generation_started_at` хранится в Python session snapshot, поэтому browser
refresh не сбрасывает таймер выполняющегося ответа. Счётчик в header показывает
context usage последнего assistant message и `limit.context` выбранной модели из
OpenCode configuration. Название берётся у OpenCode, а при его отсутствии
создаётся короткий fallback; ручное переименование через web UI также обновляет
OpenCode session.

## Диагностика

Для AI issue сохраните:

- workflow/session ID и ссылку на OpenCode web session;
- model + thinking variant;
- tool name/status/duration и раскрываемые sanitized input/output;
- AutoDeploy server request ID и error type;
- состояние OpenCode connection и MCP connections.

Не копируйте в issue raw ticket, token, full repository file или `.env`.
500/502 не следует маскировать retry loop: fatal provider/schema error должен
завершить turn один раз с понятным сообщением и сохранённой session для анализа.

## Acceptance checks

- greeting отвечает без catalog и form tools;
- form query лениво создаёт один form-search session и переиспользует её;
- положительные/отрицательные routing examples выбирают ожидаемые candidates;
- selected form schema запрашивается только после routing;
- SELECT/MULTISELECT разрешаются через form reference, не repository guessing;
- simple request не создаёт Researcher; complex bounded case создаёт и удаляет;
- AI draft переживает restart, открывается по старой ссылке и не submitится сам;
- tool permissions соответствуют exact allowlists;
- plugin видимость и каждая operation policy fail-closed; manual спрашивает
  approval на каждый вызов, deny блокирует stale session;
- `git_pull` всегда спрашивает approval;
- logs/chat не раскрывают secrets и unrelated repository content.
