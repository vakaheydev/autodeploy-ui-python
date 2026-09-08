# Инструкция корпоративному AI-агенту

Эта инструкция предназначена для корня private repository `corp-autodeploy`.
Агент работает с корпоративной реализацией, а не с публичным ядром.

## Перед любой задачей

1. Прочитайте `docs/README.md` и только документы, связанные с задачей.
2. Проверьте branch, `git status` и пользовательские изменения.
3. Определите зафиксированную версию `gravitee-autodeploy`, установленную в
   тестовом окружении или указанную в `pyproject.toml`.
4. Откройте актуальный публичный контракт этой версии. Не восстанавливайте его
   по памяти и не копируйте реализацию из старого Tkinter-проекта.
5. Сформулируйте затрагиваемый extension point и тест до изменения.

## Неподвижные архитектурные правила

- Вся бизнес-логика формы остаётся в Python: поля, defaults, conditions,
  validation, references, payload, endpoint, auth, actions, submit и polling.
- React — generic renderer. Корпоративный package не содержит fork frontend и
  не передаёт браузеру URL, credentials или callable.
- Private code подключается только через публичные import contracts и шесть
  runtime extension points: form registrar, plugin registrar, services,
  reference handlers, search catalogs и environment hook. Update provider
  является отдельной launcher границей.
- Реальные ITSM/TFS/Gravitee реализации, справочники и формы находятся только в
  private package. Публичное ядро не редактируется из корпоративной задачи.
- Секреты читаются только server-side из пользовательского `.env`. Они не
  хранятся в исходниках, wheel, fixture, snapshot, exception для пользователя,
  AI context или логах.
- AI может подготовить persistent draft, но не может submit/deploy. Любой
  внешний side effect проходит через обычный Python form lifecycle и явное
  подтверждение пользователя.
- Новая web-функциональность не должна зависеть от `self.screen`, Tkinter widget
  или dialog. Для кнопок используйте `ServerAction`; для окружения —
  `self.current_environment` или аргумент hook.
- Corporate custom pages объявляются через `PluginDefinition`. Не добавляйте
  private React/HTML: поля, виджеты и операции возвращаются публичному generic
  renderer, а интеграции доступны только через `PluginContext.services`.
- Plugin AI policy закрыта по умолчанию. Агент не должен сам включать видимость
  или менять `deny/manual/allow`; это операторская настройка.

## Владение файлами

Рекомендуемый namespace — `src/corp_autodeploy/`. Не создавайте top-level
пакеты `forms`, `services`, `config`, `handlers` или `webapp`: они конфликтуют с
публичным wheel.

| Область | Корпоративный владелец |
|---|---|
| Регистрация и AI routing | `corp_autodeploy.registrar` |
| Формы | `corp_autodeploy.forms.*` |
| Custom page плагины | `corp_autodeploy.plugins.*` |
| ITSM/TFS/Gravitee adapters | `corp_autodeploy.services` или `integrations/` |
| Справочники | `corp_autodeploy.references` + private package data |
| Глобальный поиск | `corp_autodeploy.search_catalogs` |
| Смена окружения | `corp_autodeploy.environment` |
| Update delivery | `corp_autodeploy.update_provider` |

## Правила изменений

- Сохраняйте стабильными `form_id` и field keys: на них ссылаются drafts,
  история, AI routing и внешние клиенты.
- У каждой зарегистрированной формы должно быть ровно одно актуальное
  `FormRoutingDescription` без полей, справочников и секретов.
- В condition используйте безопасный доступ: `lambda values:
  bool(values.get("flag"))`. Runtime вычисляет condition и на неполном состоянии.
- `SELECT` хранит один `value_key`; `MULTISELECT` — список `value_key`.
  Никогда не подменяйте ID отображаемым `label_key`.
- Domain errors возвращайте через `self.validation_error(field, message)`, чтобы
  web UI показал ошибку у поля и сфокусировал его.
- Network errors должны сохранять диагностическую причину в server log, но
  отдавать пользователю безопасный текст без auth headers и raw secrets.
- Долгие и повторяемые операции делайте идемпотентными. Environment hook и
  reference handler могут вызываться несколькими вкладками.
- Plugin `render` вызывается при открытии и изменении полей: он read-only и
  быстрый. Side effects и долгие расчёты оформляйте как `PluginOperation`.

## Проверка результата

Минимум для каждой задачи:

1. unit tests private package;
2. integration tests с установленным зафиксированным public wheel;
3. form state/validation/preview через REST, если менялась форма;
4. reference search для каждого environment, если менялся справочник;
5. проверка redaction в исключениях и логах;
6. сборка private wheel и установка его в чистое virtual environment;
7. smoke test итогового offline release, если менялась поставка.

Для plugin change дополнительно проверьте dynamic widgets, operation
confirmation и все три AI policy (`deny`, `manual`, `allow`).

Не заявляйте готовность только по импорту модуля. Для form change сравните
ожидаемый payload, auth type и endpoint; для AI routing проверьте хотя бы один
положительный и один отрицательный запрос; для hook проверьте success, safe
rejection и rollback выбора окружения.

## Когда требуется изменение публичного ядра

Остановитесь и вынесите отдельную задачу в public repository, если нужного
contract нет или приходится импортировать `_private_name`, monkey-patch runtime
либо повторять server lifecycle. Публичное изменение должно быть обратно
совместимым, покрытым тестами и одновременно отражено в этой документации.
