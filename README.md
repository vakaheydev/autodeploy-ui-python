# Gravitee AutoDeploy

Gravitee AutoDeploy теперь доступен как локальное веб-приложение: один Python
процесс публикует versioned REST API и уже собранный React-интерфейс на одном
localhost-порту. Вся схема форм, валидация, payload, авторизация, отправка,
опрос результата и интеграционная логика остаются в Python.

Исходный Tkinter-клиент сохранён и запускается командой
`python main.py`. Новый сервер запускается командой `python -m webapp` и по
умолчанию открывается на `http://127.0.0.1:8765`.

Инструкции по production-установке, обновлению и корпоративным расширениям:
[docs/INSTALLATION.md](docs/INSTALLATION.md) и
[docs/WEB_ARCHITECTURE.md](docs/WEB_ARCHITECTURE.md).

Пошаговый перенос закрытых форм, ITSM/TFS/Gravitee-сервисов и справочников в
отдельный корпоративный wheel описан в
[docs/CORPORATE_MIGRATION.md](docs/CORPORATE_MIGRATION.md).

Корпоративная подготовка при смене рабочего окружения подключается отдельным
hook по инструкции
[docs/CORPORATE_ENVIRONMENT_HOOK.md](docs/CORPORATE_ENVIRONMENT_HOOK.md).

Опциональный same-port MCP и его инструменты описаны в
[docs/MCP.md](docs/MCP.md).

Архитектура Copilot, ленивого поиска форм, Python-черновиков и изолированного
Repository Researcher зафиксирована в
[docs/AI_AGENT_ARCHITECTURE.md](docs/AI_AGENT_ARCHITECTURE.md).
