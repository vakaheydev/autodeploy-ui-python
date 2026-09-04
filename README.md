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
