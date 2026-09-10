# Тестирование и поставка

## Локальная разработка двух пакетов

Рекомендуемый layout checkout:

```text
workspace/
├── gravitee-autodeploy/   # public core
└── corp-autodeploy/       # private package
```

Оба package устанавливаются в одно disposable virtual environment. Windows:

```powershell
cd workspace\gravitee-autodeploy
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[test]"
.\.venv\Scripts\python.exe -m pip install -e ..\corp-autodeploy --no-deps
$env:AUTODEPLOY_ENV_FILE = "C:\safe\path\autodeploy.env"
.\.venv\Scripts\python.exe -m webapp
```

Linux/macOS:

```bash
cd workspace/gravitee-autodeploy
python -m venv .venv
.venv/bin/python -m pip install -e ".[test]"
.venv/bin/python -m pip install -e ../corp-autodeploy --no-deps
AUTODEPLOY_ENV_FILE=/safe/path/autodeploy.env .venv/bin/python -m webapp
```

`--no-deps` у private editable install предотвращает поиск public package в
PyPI: он уже установлен из соседнего checkout. Это только developer workflow,
не release installation.

После startup проверьте:

- `GET http://127.0.0.1:8765/api/v1/health`;
- `GET http://127.0.0.1:8765/api/docs`;
- catalog и нужную форму через browser;
- server log на отсутствие import/configuration errors.

## Test pyramid

### Unit

Private tests без сети проверяют:

- `build_payload`, `validate`, endpoints и routing descriptions;
- plugin render/validate, operation handlers и безопасную сериализацию widgets;
- parsing/mapping ITSM, TFS, Gravitee responses;
- reference handler transformation, params и redaction;
- environment/update factories;
- auth selection и safe error messages.

Используйте fake adapters и synthetic data. Реальные tickets/tokens/definitions
не должны попадать в fixtures и snapshots.

### Contract

Установите pinned public wheel и private wheel, затем проверьте:

- все import paths из `.env` загружаются;
- registrar не оставляет missing/unknown form routing;
- plugin registrar возвращает уникальные definitions, а страницы и операции
  соответствуют публичному contract;
- form documents JSON-serializable;
- initial `/state`, every condition branch, `/validate` и `/preview`;
- reference options, selected-first behavior и dependencies;
- environment hook 422 contract;
- secrets остаются write-only в `/settings`;
- AutoDeploy MCP tools видят private forms/references при enabled flag;
- plugin AI policy по умолчанию закрыта; `allow`, `manual` и последующий `deny`
  дают ожидаемый набор MCP tools и fail-closed dispatch.

Contract tests должны падать при несовместимом обновлении public core до выпуска
release.

### Integration/E2E

На разрешённых test systems проверьте:

- ITSM/TFS/Gravitee auth и certificate;
- exact payload/headers/endpoint без production write;
- submit error остаётся в modal и повторная попытка работает;
- polling завершается ожидаемым status;
- AI semantic routing, reference resolution и persistent draft;
- plugin catalog, shared fields/references/widgets, browser confirmation и
  operation в светлой и тёмной теме;
- light/dark UI только через public frontend E2E, без private frontend fork.

## Обязательный pre-release gate

1. Собрать и протестировать private wheel.
2. Запустить public Python tests и frontend tests/build.
3. Запустить private unit + contract suite с exact public version.
4. Собрать offline archive с private wheels.
5. Установить archive в пустой temp directory.
6. Запустить server из установленной version и проверить health, SPA, catalog,
   одну representative preview, одну representative plugin page и private
   package import.
7. Проверить rollback.
8. Опубликовать immutable archive.
9. Проверить его SHA-256.
10. Только затем атомарно опубликовать manifest.

## Сборка private wheel

```powershell
cd workspace\corp-autodeploy
python -m pytest
python -m build --wheel
```

Результат находится в `dist/corp_autodeploy-<version>-py3-none-any.whl`.
Проверьте contents wheel: там не должно быть `.env`, certificates, logs, caches,
test data с реальными значениями и старого Tkinter tree.

## Сборка общего offline release

Frontend собирается на CI/developer machine; пользователю Node/npm не нужен.
Из public checkout:

```powershell
python scripts/build_release.py `
  --artifact-url "https://tfs.example/releases/gravitee-autodeploy-1.4.0.zip" `
  --extra-wheel "..\corp-autodeploy\dist\corp_autodeploy-1.4.0-py3-none-any.whl" `
  --extra-wheel "C:\wheelhouse-input\requests-2.32.3-py3-none-any.whl" `
  --wheel-platform win_amd64 `
  --python-version 310 --python-version 311 `
  --python-version 312 --python-version 313
```

`--extra-wheel` повторяется для private package и каждой его dependency, которой
нет в public `requirements-web.txt`. End-user installer работает offline с
`--no-index`; отсутствие transitive wheel обнаружится только на чистой установке,
поэтому smoke test обязателен.

Outputs в `build/release/`:

- `gravitee-autodeploy-app-<version>.zip` — immutable updater artifact;
- `gravitee-autodeploy-installer-<version>.zip` — bootstrap installer;
- `update-manifest.json` — указатель на опубликованный artifact.

Проверка готового application archive:

```powershell
python scripts/verify_release.py `
  build\release\gravitee-autodeploy-app-1.4.0.zip
```

Public verification запускает installed server и public representative form.
Corporate pipeline должен дополнительно проверить, что private registrar и
representative private form действительно загружены.

## Manifest и версии

`version.txt` public build содержит SemVer в первой строке, затем пустую строку и
changelog. Builder создаёт manifest:

```json
{
  "schema_version": 1,
  "version": "1.4.0",
  "artifact_url": "https://tfs.example/releases/gravitee-autodeploy-1.4.0.zip",
  "sha256": "64 lowercase hex characters",
  "size": 12345678,
  "changelog": "Изменения этой версии",
  "minimum_launcher_version": "1.0.0"
}
```

Не пересобирайте уже опубликованную SemVer с другим содержимым. Archive сначала
upload как immutable object; manifest заменяется последним atomic step.

Default TFS update provider использует Basic PAT с пустым username, принимает
только HTTPS (loopback HTTP — test exception), не принимает credentials в URL,
не переносит Authorization при redirect на другой host, ограничивает размеры и
проверяет SHA-256.

## Custom update provider

Если default TFS protocol недостаточен:

```python
from pathlib import Path

from launcher.manifest import ReleaseManifest


class CorporateUpdateProvider:
    def fetch_manifest(self) -> ReleaseManifest:
        ...

    def download(self, manifest, destination: Path, progress=None) -> Path:
        ...


def create_provider(paths, values):
    return CorporateUpdateProvider(...)
```

```dotenv
AUTODEPLOY_UPDATE_PROVIDER=corp_launcher_provider:create_provider
```

Factory получает launcher `InstallPaths` и parsed `.env` mapping. Provider не
должен логировать mapping или сохранять secret в artifact. Он обязан скачать во
временный `.part`, проверить integrity/size и атомарно завершить destination.

Важно: launcher работает системным Python до запуска version-specific app
`.venv`. Поэтому callable, находящийся только внутри `corp-autodeploy` wheel, в
этот момент недоступен. Corporate pipeline должен отдельно положить dependency-
free module на `sys.path` установленного launcher либо собрать его внутрь
launcher payload. Если такой packaging не настроен, используйте стандартный
`AUTODEPLOY_UPDATE_MANIFEST_URL`, а не custom provider.

## Установка и rollback

Пользователь распаковывает installer ZIP и запускает `install.cmd` (или
`python install.py`). Launcher создаёт version-specific `.venv`; global Python
packages не используются. Mutable `config/.env`, `data/` и `logs/` находятся
вне version folder и переживают update.

`data/plugin-ai-policy.json` и `data/itsm-ai-prompts.json` относятся к mutable
operator state: release archive не должен включать или перезаписывать их. При
первом запуске либо появлении новой plugin operation policy автоматически
остаётся `deny`, пока оператор явно не изменит её в UI. Отсутствующий файл ITSM
prompts означает использование corporate hook; повреждённый файл должен попасть
в backup/диагностику, но не заменяться updater-ом.

Activation — atomic pointer на installed version. Если новый server не проходит
health check, launcher один раз возвращается на предыдущую version. Ручной
rollback:

```powershell
python -m launcher rollback
```

## Release evidence

Сохраняйте в pipeline artifacts:

- public/private version и commit IDs;
- test reports;
- wheel inventory по поддерживаемым Python/platform;
- app archive SHA-256 и manifest;
- sanitized smoke-test health/catalog result;
- rollback result.

Никогда не прикладывайте заполненный `.env`, auth headers, raw ITSM responses или
corporate definitions.
