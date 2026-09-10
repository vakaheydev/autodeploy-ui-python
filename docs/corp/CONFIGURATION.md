# Конфигурация и секреты

## Где хранится `.env`

Установленный launcher хранит изменяемые данные вне immutable version:

```text
<install-root>/
├── config/.env
├── data/
├── logs/
└── versions/<version>/
```

Update сохраняет `config/.env`, drafts, history, logs и OpenCode runtime.
Разработчик может явно задать файл process variable:

```text
AUTODEPLOY_ENV_FILE=/absolute/path/to/.env
```

Без override server использует legacy `.env` в project root, если он существует,
иначе per-user data directory. Process environment имеет приоритет над saved
`.env`; изменение такого key во frontend не переопределит process-level value
до изменения способа запуска.

## Corporate template

Не храните заполненный файл в Git. Комментарии и пустой template допустимы:

```dotenv
# Runtime
AUTODEPLOY_PORT=8765
AUTODEPLOY_OPENCODE_AUTO_CONNECT=true
AUTODEPLOY_OPEN_BROWSER=true
AUTODEPLOY_MAX_REQUEST_BYTES=2097152
AUTODEPLOY_MCP_ENABLED=false

# User/corporate secrets
LOGIN=
TFS_TOKEN=
ITSM_LOGIN=
ITSM_PASSWORD=
GRAVITEE_TOKEN_TEST_INT=
GRAVITEE_TOKEN_TEST_EXT=
GRAVITEE_TOKEN_REGRESS_INT=
GRAVITEE_TOKEN_REGRESS_EXT=
GRAVITEE_TOKEN_PROD_INT=
GRAVITEE_TOKEN_PROD_EXT=

# Optional corporate paths
GRAVITEE_REPO_PATH=
CERT_PATH=

# OpenCode connection; provider credentials stay in OpenCode config
OPENCODE_SERVER_URL=http://127.0.0.1:4096
OPENCODE_SERVER_USERNAME=opencode
OPENCODE_SERVER_PASSWORD=
OPENCODE_CONNECT_TIMEOUT=10
OPENCODE_STARTUP_TIMEOUT=20
OPENCODE_REQUEST_TIMEOUT=120
OPENCODE_PROVIDER_ID=
OPENCODE_MODEL_ID=
OPENCODE_ALLOWED_MCP=
OPENCODE_REPOSITORY_MCP=
OPENCODE_REPOSITORY_GIT_PULL=true

# Private package composition
AUTODEPLOY_FORM_REGISTRAR=corp_autodeploy.registrar:register_forms
AUTODEPLOY_PLUGIN_REGISTRAR=corp_autodeploy.plugins.registrar:register_plugins
AUTODEPLOY_SERVICE_PROVIDER=corp_autodeploy.services:create_services
AUTODEPLOY_REFERENCE_HANDLER_FACTORY=corp_autodeploy.references:create_handlers
AUTODEPLOY_SEARCH_CATALOG_FACTORY=corp_autodeploy.search_catalogs:create_search_catalogs
AUTODEPLOY_ENVIRONMENT_HOOK=corp_autodeploy.environment:create_environment_hook
AUTODEPLOY_TICKET_PROVIDER=corp_autodeploy.tickets:create_ticket_provider

# Launcher delivery
AUTODEPLOY_UPDATE_MANIFEST_URL=
AUTODEPLOY_UPDATE_PROVIDER=
AUTODEPLOY_UPDATE_TIMEOUT=30
```

AI context limits и inline-reference limits также доступны на странице
OpenCode settings. Оставляйте public defaults, пока нет измеренного основания
для изменения.

## AI-инструкции по типам ITSM-заявок

Многострочные правила `ticket_type → prompt` настраиваются во frontend:
**Настройки → ITSM и AI**. Они сохраняются отдельно от секретов в
`<AUTODEPLOY_DATA_DIR>/itsm-ai-prompts.json` и начинают действовать для
следующей загружаемой заявки без restart.

Корпоративный `ITSMService.get_ai_prompt(...)` остаётся источником
`ticket_type` и fallback-инструкций. Полный контракт и порядок приоритетов:
[ITSM_FORM_FILLING.md](ITSM_FORM_FILLING.md#настройка-prompt-через-frontend).

Это отдельный typed settings API, а не произвольный редактор `.env` или JSON.
Frontend разрешает добавить до 100 правил, подсвечивает несохранённые карточки,
проверяет пустые/повторяющиеся типы и показывает server-side validation error.
Сравнение типов выполняется без учёта регистра и внешних пробелов; сохранённое
имя остаётся читаемым для оператора. Один prompt ограничен 16 000 символами.

Файл относится к mutable operator state:

- включайте его в backup вместе с `drafts/`, history и plugin AI policy;
- не кладите его в release archive и не перезаписывайте updater-ом;
- не редактируйте одновременно вручную и через UI;
- при повреждении файла UI показывает warning, а runtime безопасно возвращается
  к fallback prompt корпоративного hook;
- удаление правила в UI не удаляет тип из corporate service, а лишь возвращает
  поведение к code fallback.

Prompt — доверенная инструкция модели, хотя secret setting им не является.
Доступ к этой вкладке означает право менять поведение AI. Не помещайте туда raw
текст заявки, персональные данные, токены, private URL с credentials или
инструкции обхода preview/validation/confirmation.

## Frontend settings

Страница **Настройки** работает только с whitelist public core. Она:

- группирует runtime, access, OpenCode, extensions и updates;
- показывает field-local HTTP 422 validation error;
- подсвечивает изменённые поля;
- показывает Save/Reset panel только после первого изменения;
- использует file/directory picker для разрешённых path settings;
- использует MCP pickers из фактической OpenCode configuration;
- редактирует typed ITSM AI-prompts без ручной правки JSON;
- сообщает, когда нужен restart или reconnect.

Secret fields write-only. API возвращает только `configured: true/false`, но не
stored value. Browser может заменить secret либо явно очистить его. Не пытайтесь
реализовать «показать текущий token»: это нарушение security boundary.

Extension factories и `AUTODEPLOY_MCP_ENABLED` применяются после полного restart,
потому что входят в composition root. OpenCode connection settings можно
переподключить через UI; новые MCP permissions применяются к новой AI session.

Отдельная вкладка **Настройки -> Плагины** хранит не секреты и не import paths,
а operator policy для AI: глобальную видимость, видимость каждой страницы и
`deny/manual/allow` для каждой операции. Policy хранится в mutable
`data/plugin-ai-policy.json` и должна сохраняться updater наравне с drafts.
После расширения permissions нужен новый AI chat; запрет проверяется runtime и
для уже существующей сессии. Подробности — в [PLUGINS.md](PLUGINS.md).

## OpenCode configuration

AutoDeploy `.env` хранит только адрес/Basic auth локального OpenCode server,
выбранный provider/model и MCP names. Credentials AI provider, model catalog,
variants и определения MCP остаются в глобальной конфигурации OpenCode.

URL должен быть локальным (`127.0.0.1`/`localhost`). Если server создан
AutoDeploy, он также binds localhost. Один OpenCode server может одновременно
обслуживать AutoDeploy и browser client; sessions разделяются ID.

При `AUTODEPLOY_OPENCODE_AUTO_CONNECT=true` server делает попытку подключиться к
`OPENCODE_SERVER_URL` при startup. Это не означает автоматически «создать
OpenCode process»: подключение и создание — разные явные действия UI.

Всегда выбирайте provider/model явно при создании session, даже если UI показывает
default. Thinking variant должен быть одним из вариантов фактической model
configuration.

## Добавление собственного secret/config key

Private package не может автоматически публиковать произвольные `.env` keys во
frontend: whitelist принадлежит public core. Предпочтительный порядок:

1. если setting должен быть UI-editable, добавить typed `SettingSpec` в public
   core, validation и secret classification;
2. если setting server-only, оставить его private и редактировать в managed
   `.env` вне browser;
3. читать значение через injected `EnvManager.get("CORP_KEY")`;
4. не сохранять secret в class attribute дольше request;
5. покрыть snapshot/update/redaction tests.

Не используйте generic endpoint «прочитать весь `.env`» и не передавайте private
configuration в form schema.

## Security checklist

- `.env`, certificates и local tokens исключены из Git и release wheel;
- installer/update никогда не затирает `config/.env` и `.venv` active version
  атомарно заменяется только внутри release directory;
- logs не содержат secret values, Authorization или URL credentials/query;
- `OPENCODE_SERVER_PASSWORD` не попадает в model context;
- private dictionary detail keys не публикуют confidential fields;
- file picker перечисляет metadata путей, но не читает содержимое файлов;
- server binds только `127.0.0.1`/`localhost`;
- `.env` permissions ограничены текущим пользователем средствами deployment;
- production URLs используют HTTPS и проверенный corporate certificate.

## Диагностика startup

При ошибке import path проверьте в том же interpreter:

```bash
python -c "import corp_autodeploy; print(corp_autodeploy.__file__)"
python -c "from corp_autodeploy.registrar import register_forms; print(register_forms)"
```

Затем проверьте, какой `.env` реально выбран через process
`AUTODEPLOY_ENV_FILE`, и перезапустите server. Не печатайте `env_manager.load()`
целиком: выводите только имя key и boolean `configured`.
