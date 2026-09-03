# AI-автозаполнение через OpenCode

Интеграция рассчитана на OpenCode `1.18.18`. Приложение само запускает локальный
сервер; от пользователя требуется установленная команда `opencode` в `PATH` и
настроенный provider в самом OpenCode.

## Первичная настройка

1. Проверьте команду:

   ```bash
   opencode --version
   ```

2. В обычном экране **Настройки** заполните:

   - `ITSM_LOGIN` и `ITSM_PASSWORD`;
   - **Ticket URL template**, например
     `https://itsm.example/api/tickets/{ticket_id}`;
   - `TFS_TOKEN`;
   - **PR URL template**, если заявка содержит только числовой PR ID, например
     `https://dev.azure.com/org/project/_git/repo/pullrequest/{pull_request_id}`;
   - **Allowed hosts** для корпоративных ADO-хостов через запятую. Для
     `dev.azure.com` и `*.visualstudio.com` отдельная запись не нужна.

3. На самом главном экране откройте четвёртую карточку **OpenCode**. Там доступны:

   - состояние, версия, localhost-адрес, PID и результат загрузки агента;
   - запуск, перезапуск и остановка сервера;
   - проверка provider;
   - необязательные `Provider ID` и `Model ID`;
   - startup/request timeout и лимит контекста.

`Provider ID` и `Model ID` заполняются только вместе. Если оба пусты, запрос
использует модель OpenCode по умолчанию. API key приложение не читает и не
сохраняет — credentials остаются в конфигурации OpenCode.

## Работа пользователя

В любой AutoDeploy-форме кнопка **«Подтянуть данные из заявки»** запускает такой
сценарий:

1. получение ITSM-заявки и связанного Azure DevOps PR;
2. очистка и ограничение контекста;
3. новая изолированная OpenCode session с явно выбранным `form-extractor`;
4. Structured Output по схеме текущей формы;
5. независимая schema/domain-валидация в Python;
6. редактируемый preview;
7. изменение основной формы только после явного применения.

В preview можно оставить только выбранные изменения, применить все валидные,
вернуть AI-предложение, вернуть текущее значение, очистить поле или отменить
операцию целиком. Значения с `low` confidence не выбраны по умолчанию и отмечены
предупреждением.

## Запуск и остановка сервера

На старте приложения менеджер выполняет `opencode --version`, выбирает свободный
порт и запускает:

```text
opencode serve --hostname 127.0.0.1 --port <PORT>
```

Затем проверяются `GET /global/health` и наличие `form-extractor` через
`GET /agent`. Адрес с любым host, кроме точного `127.0.0.1`, клиент отвергает.
При закрытии приложения процесс и его дочерняя process group завершаются.

Если OpenCode недоступен, AI-кнопка показывает диагностику, но поиск, формы,
операции и обычный submit продолжают работать.

## Контракт OpenCode 1.18.18

Каждый message явно передаёт:

```json
{
  "agent": "form-extractor",
  "format": {
    "type": "json_schema",
    "schema": {},
    "retryCount": 2
  }
}
```

В OpenCode `1.18.18` финальное значение находится в `info.structured`. Клиент
читает это фактическое поле и оставляет совместимость с именами
`structured_output` / `structuredOutput`. Текст ответа не используется как
fallback: отсутствие Structured Output или `StructuredOutputError` закрывает
операцию без preview.

## Границы безопасности

- `.opencode/agents/form-extractor.md` — отдельный primary agent.
- Catch-all permission запрещает все инструменты; разрешён только внутренний
  `StructuredOutput`, необходимый для JSON Schema.
- ITSM, PR, comments, changes и справочники передаются как недоверенные данные в
  явно ограниченных секциях prompt.
- Секретные ключи/заголовки, Bearer/Basic, JWT и private keys редактируются до
  отправки; сырой контекст и stdout OpenCode не сохраняются.
- ADO URL принимаются только по HTTPS и только для allowlist-хостов.
- Неизвестное значение справочника нельзя предложить, если допустимый список не
  был успешно загружен.
- SSE меняет только текст прогресса; preview строится исключительно из финального
  `structured` после Python-валидации.
- Одна заявка использует одну session; после успеха, ошибки или отмены session
  удаляется.

## Проверки

```bash
python -m unittest discover -v
python -m compileall -q .
```

Unit-тесты используют временный HTTP server только на `127.0.0.1`. Для полного
интеграционного smoke-test нужен установленный OpenCode `1.18.18` и настроенный
provider.
