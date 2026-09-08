# Корпоративный hook переключения окружения

Веб-клиент перед сменой рабочего окружения вызывает серверный endpoint
`POST /api/v1/environments/activate`. Публичное ядро проверяет ключ окружения и,
если настроено корпоративное расширение, синхронно вызывает его hook. Только
после успешного ответа браузер сохраняет новое окружение и перезагружает форму
и справочники. При ошибке старое окружение остаётся выбранным, а сообщение
показывается рядом с переключателем.

Hook нужен для корпоративной подготовки, которую необходимо выполнить один раз
на явный переход пользователя: например, проверить доступность контура,
обновить локальный read-only snapshot или переключить legacy-клиент. Обычные
сервисы, формы и справочники всё равно должны принимать `environment` явно и не
полагаться на глобальное текущее окружение.

## 1. Создайте модуль в закрытом пакете

Например, добавьте файл `corp-autodeploy/src/corp_autodeploy/environment.py`:

```python
from __future__ import annotations

from core.env_manager import EnvManager
from webapp.extensions import EnvironmentChangeRejected


def create_environment_hook(env_manager: EnvManager):
    """Factory вызывается один раз при запуске Python-сервера."""

    def on_environment_changed(
        previous_environment: str | None,
        environment: str,
    ) -> None:
        """Hook вызывается до фиксации нового окружения во frontend."""
        try:
            # Здесь вызывайте только корпоративную реализацию.
            # prepare_corporate_environment(
            #     environment=environment,
            #     previous_environment=previous_environment,
            #     token=env_manager.get("CORP_TOKEN"),
            # )
            pass
        except KnownCorporateError as exc:
            # Этот текст безопасно увидит пользователь. Не включайте секреты,
            # заголовки Authorization и необработанные ответы сервисов.
            raise EnvironmentChangeRejected(
                f"Не удалось подготовить окружение {environment}"
            ) from exc

    return on_environment_changed
```

Замените `KnownCorporateError` на исключение вашей интеграции либо удалите блок
`try/except`, если он пока не нужен. Factory обязан вернуть callable с двумя
позиционными аргументами:

```text
hook(previous_environment: str | None, environment: str) -> None
```

- `previous_environment` — прежний ключ (`test_int`, `prod_ext` и так далее),
  либо `None`, если прежнее значение браузера уже отсутствует в каталоге;
- `environment` — проверенный новый ключ;
- нормальное завершение означает разрешение перехода;
- `EnvironmentChangeRejected("безопасный текст")` отклоняет переход с HTTP 422;
- любое другое исключение тоже отклоняет переход, но его текст скрывается от
  браузера и полностью попадает только в серверный лог.

## 2. Подключите hook

Убедитесь, что закрытый wheel установлен в том же Python-окружении, что и
публичное ядро, и добавьте import path в серверный `.env`:

```env
AUTODEPLOY_ENVIRONMENT_HOOK=corp_autodeploy.environment:create_environment_hook
```

То же значение можно внести через `Настройки` → `Расширения` →
`Фабрика hook переключения окружения`. Настройка применяется после полного
перезапуска Python-сервера, потому что factory загружается один раз при старте.

## 3. Проверьте вручную

1. Перезапустите `python -m webapp`.
2. Откройте AutoDeploy и выберите другое окружение в верхней панели.
3. Во время работы hook рядом с выбором появится `Переключаю…`.
4. При успехе новое окружение будет сохранено, после чего форма запросит новую
   серверную схему и справочники.
5. Для проверки отказа временно выбросьте
   `EnvironmentChangeRejected("Тестовый отказ")`: интерфейс должен оставить
   прежнее окружение и показать этот текст рядом с переключателем.

Прямой тест API:

```http
POST http://127.0.0.1:8765/api/v1/environments/activate
Content-Type: application/json

{
  "previous_environment": "test_int",
  "environment": "regress_int"
}
```

Успешный ответ содержит `environment`, `previous_environment`, `changed` и
`hook_configured`. Повторная активация того же значения возвращает
`changed: false` и не вызывает корпоративный hook.

## 4. Логи и требования к реализации

Начало, завершение, отказ и авария hook логируются под именем
`web.environment` в терминал и в ротационный файл `autodeploy.log`. По умолчанию
он находится в пользовательском каталоге данных:

- Windows: `%LOCALAPPDATA%\GraviteeAutoDeploy\logs\autodeploy.log`;
- Linux: `~/.local/share/gravitee-autodeploy/logs/autodeploy.log`.

Путь можно переопределить переменной процесса `AUTODEPLOY_LOG_DIR`.

Все вызовы одного hook выполняются последовательно, даже если несколько вкладок
пытаются переключиться одновременно. Тем не менее корпоративный код должен быть
идемпотентным и по возможности быстрым: запрос браузера ждёт его завершения.
Не храните секреты в замыкании без необходимости, не логируйте `.env` и не
возвращайте в `EnvironmentChangeRejected` чувствительные ответы. Долгие загрузки
лучше делать в корпоративном кеше, а hook использовать для проверки или
атомарного переключения уже подготовленного состояния.

## 5. Минимальный unit-тест закрытого hook

```python
from core.env_manager import EnvManager

from corp_autodeploy.environment import create_environment_hook


def test_environment_hook(tmp_path):
    env = EnvManager(tmp_path / ".env")
    hook = create_environment_hook(env)

    assert hook("test_int", "regress_int") is None
```

Для сетевой корпоративной реализации подмените клиент/adapter и отдельно
проверьте успешный переход, ожидаемый `EnvironmentChangeRejected` и отсутствие
секретов в пользовательском сообщении.
