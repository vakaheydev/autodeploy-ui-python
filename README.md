# Gravitee AutoDeploy

Gravitee AutoDeploy — локальное web-приложение для корпоративных операций с
Gravitee. Один Python-процесс публикует versioned REST API, optional MCP и
предварительно собранный React-интерфейс на одном localhost-порту. Python
остаётся единственным источником бизнес-логики: формы, условия, справочники,
валидация, payload, авторизация, submit и polling не дублируются во frontend.

```bash
python -m venv .venv
.venv/bin/python -m pip install -e ".[test]"
AUTODEPLOY_OPENCODE_AUTO_CONNECT=false .venv/bin/python -m webapp
```

После запуска:

- приложение: `http://127.0.0.1:8765`;
- OpenAPI: `http://127.0.0.1:8765/api/docs`;
- optional Streamable HTTP MCP: `http://127.0.0.1:8765/api/mcp`.

## Документация

Начните с [индекса документации](docs/README.md). Для публичного ядра доступны:

- [web-архитектура](docs/WEB_ARCHITECTURE.md);
- [архитектура AI-агентов](docs/AI_AGENT_ARCHITECTURE.md);
- [AutoDeploy MCP](docs/MCP.md);
- [установка, сборка и доставка](docs/INSTALLATION.md).

Корпоративная реализация живёт в отдельном private Python package и подключается
через стабильные extension points. Самодостаточная документация для её
разработчиков и AI-агентов находится только в [docs/corp/](docs/corp/README.md).
Эту папку можно целиком скопировать в закрытый репозиторий.

Раздел **Плагины** позволяет private package добавлять полноценные server-driven
custom pages с общими полями/справочниками форм, динамическими графиками и
картинками, Python-операциями и отдельной fail-closed AI policy. Контракт и
готовый шаблон находятся в [docs/corp/PLUGINS.md](docs/corp/PLUGINS.md).

Tkinter entry point `python main.py` сохранён только для совместимости. Новые
возможности и корпоративные интеграции следует развивать через Python server и
web UI.
