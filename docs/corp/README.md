# Корпоративная реализация Gravitee AutoDeploy

Это самодостаточная документация для private-пакета `corp-autodeploy`. Здесь
описано только текущее целевое состояние web-решения. Инструкций по переносу из
старого Tkinter-монолита намеренно нет.

Публичное ядро и корпоративная реализация поставляются раздельно:

```text
gravitee-autodeploy (public core)       corp-autodeploy (private package)
├── FastAPI + React                     ├── корпоративные формы
├── form/plugin runtime contracts       ├── custom page плагины
├── ticket workspace contracts          ├── ITSM list/card/action provider
├── generic UI renderer                 ├── ITSM/TFS/Gravitee adapters
├── AI, MCP, drafts                     ├── HTTP/local справочники
├── launcher/updater                    ├── environment/update hooks
└── безопасные заглушки                 └── routing-описания форм
                 └──── единый offline release ────┘
```

Frontend никогда не импортирует private code. Оба Python wheel устанавливаются
в одно виртуальное окружение, а private package подключается через import paths
в пользовательском `.env`.

## Как использовать эту папку

Скопируйте папку целиком в закрытый репозиторий, например как `docs/`. Чтобы
корпоративный AI-агент автоматически получил правила, скопируйте также
`AGENTS.md` из этой папки в корень private repository. Не смешивайте этот
handbook с документацией публичного ядра.

Рекомендуемый порядок чтения агентом:

1. [AGENTS.md](AGENTS.md) — границы, workflow и критерии готовности.
2. [ARCHITECTURE.md](ARCHITECTURE.md) — структура пакета и extension points.
3. Документ по задаче:
   - [FORMS.md](FORMS.md) — формы, actions, submit и совместимость;
   - [ACTION_DIALOGS.md](ACTION_DIALOGS.md) — интерактивные form actions,
     диалоги, кнопки и multi-dependent references;
   - [ITSM_FORM_FILLING.md](ITSM_FORM_FILLING.md) — deterministic/AI режимы
     кнопки заявки, определение типа и prompts из frontend;
   - [PLUGINS.md](PLUGINS.md) — корпоративные custom pages, динамические
     виджеты, операции и AI policy;
   - [TICKETS.md](TICKETS.md) — список заявок, фильтры, карточки и
     корпоративные кнопки;
   - [REFERENCES_AND_SEARCH.md](REFERENCES_AND_SEARCH.md) — справочники и поиск;
   - [SERVICES_AND_ENVIRONMENT.md](SERVICES_AND_ENVIRONMENT.md) — интеграции,
     авторизация и переключение окружения;
   - [AI_AND_MCP.md](AI_AND_MCP.md) — Copilot, routing, MCP и trust boundaries;
   - [CONFIGURATION.md](CONFIGURATION.md) — `.env`, секреты и настройки;
   - [TESTING_AND_RELEASE.md](TESTING_AND_RELEASE.md) — тесты и offline delivery.

## Быстрый выбор документа

| Если меняется… | Сначала читать | Проверять в публичном ядре |
|---|---|---|
| Поля, validation, payload, submit | `FORMS.md` | `forms/base_form.py`, `forms/fields.py` |
| Диалог, доступ к полям формы, Swagger picker | `ACTION_DIALOGS.md` | `forms/base_form.py`, `forms/fields.py`, `webapp/form_runtime.py` |
| Заполнение формы из заявки | `ITSM_FORM_FILLING.md` | `forms/base_form.py`, `webapp/form_runtime.py` |
| Новый тип заявки или изменение AI prompt | `ITSM_FORM_FILLING.md`, `CONFIGURATION.md` | `opencode_integration/context_builder.py`, `webapp/itsm_prompt_settings.py` |
| Custom page, отчёт, график, plugin operation | `PLUGINS.md` | `plugins/`, `webapp/plugin_runtime.py` |
| Список/поиск заявок, карточка, ITSM-кнопка | `TICKETS.md` | `tickets/`, `webapp/ticket_runtime.py` |
| ITSM/TFS/Gravitee-клиент | `SERVICES_AND_ENVIRONMENT.md` | `webapp/extensions.py`, `services/submit_service.py` |
| SELECT/MULTISELECT, remote dictionary | `REFERENCES_AND_SEARCH.md` | `handlers/`, `webapp/form_runtime.py` |
| Выбор формы Copilot | `AI_AND_MCP.md` | `config/form_routing.py` |
| Новый env key или secret | `CONFIGURATION.md` | `config/environments.py`, `webapp/configuration.py` |
| Release и private dependency | `TESTING_AND_RELEASE.md` | `scripts/build_release.py`, `launcher/` |

## Источник истины

При расхождении приоритет таков:

1. версия публичного wheel, с которой собирается корпоративный release;
2. её Python-контракты и тесты;
3. корпоративные тесты;
4. эта документация.

Расхождение нельзя обходить копированием публичного модуля в private package.
Нужно либо адаптировать расширение к поддерживаемому контракту, либо изменить
контракт в публичном репозитории с обратной совместимостью и обновить handbook.

## Поддерживаемая граница

Корпоративному коду разрешено импортировать публичные контракты, но запрещено:

- патчить `webapp`, `forms`, `services` или `frontend` во время запуска;
- хранить реальные URL, токены, сертификаты и ответы заявок в public repository;
- дублировать Python business rules во frontend;
- обращаться к приватным атрибутам runtime;
- создавать второй submit path в обход preview, validation и подтверждения.

Для plugin operation отдельный form-submit lifecycle не требуется, но любой
внешний side effect должен быть явно названной Python-операцией. AI-доступ к ней
закрывается отдельной server-side policy и не выводится из MCP annotations.

Tkinter остаётся compatibility path, но новая функциональность проектируется для
Python server и React renderer.
