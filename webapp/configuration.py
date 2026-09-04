"""Whitelisted server-side configuration exposed to the localhost UI.

Secret values are deliberately write-only: snapshots contain only the
``configured`` flag.  The browser can replace or explicitly clear a secret,
but it can never retrieve the value stored in ``.env``.
"""
from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from typing import Any, Iterable, Mapping
from urllib.parse import urlsplit

from config.environments import (
    CERT_PATH_KEY,
    ENVIRONMENTS,
    GRAVITEE_REPO_PATH_KEY,
    ITSM_LOGIN_KEY,
    ITSM_PASSWORD_KEY,
    LOGIN_KEY,
    OPENCODE_ALLOWED_MCP_KEY,
    OPENCODE_CONNECT_TIMEOUT_KEY,
    OPENCODE_MAX_CONTEXT_CHARS_KEY,
    OPENCODE_MODEL_ID_KEY,
    OPENCODE_PROVIDER_ID_KEY,
    OPENCODE_REFERENCE_INLINE_MAX_BYTES_KEY,
    OPENCODE_REFERENCE_INLINE_MAX_ITEMS_KEY,
    OPENCODE_REFERENCE_INLINE_TOTAL_BYTES_KEY,
    OPENCODE_REPOSITORY_GIT_PULL_KEY,
    OPENCODE_REPOSITORY_MCP_KEY,
    OPENCODE_REQUEST_TIMEOUT_KEY,
    OPENCODE_SERVER_PASSWORD_KEY,
    OPENCODE_SERVER_URL_KEY,
    OPENCODE_SERVER_USERNAME_KEY,
    OPENCODE_STARTUP_TIMEOUT_KEY,
    TFS_TOKEN_KEY,
    gravitee_token_key,
)
from core.env_manager import EnvManager
from opencode_integration.manager import DEFAULT_SERVER_URL, OpenCodeManager
from webapp.extensions import (
    FORM_REGISTRAR_KEY,
    REFERENCE_HANDLER_FACTORY_KEY,
    SERVICE_PROVIDER_KEY,
)


@dataclass(frozen=True)
class SettingSpec:
    key: str
    label: str
    group: str
    kind: str = "text"  # text | secret | number | boolean | path
    default: str = ""
    description: str = ""
    required: bool = False
    restart_required: bool = False
    minimum: float | None = None
    maximum: float | None = None


def _specs() -> tuple[SettingSpec, ...]:
    access = [
        SettingSpec(LOGIN_KEY, "Логин пользователя", "Доступ", required=True),
        SettingSpec(TFS_TOKEN_KEY, "TFS / Azure DevOps token", "Доступ", "secret"),
        SettingSpec(ITSM_LOGIN_KEY, "ITSM login", "Доступ"),
        SettingSpec(ITSM_PASSWORD_KEY, "ITSM password", "Доступ", "secret"),
    ]
    access.extend(
        SettingSpec(
            gravitee_token_key(environment.key),
            f"Gravitee token · {environment.label}",
            "Доступ",
            "secret",
        )
        for environment in ENVIRONMENTS
    )
    return tuple(access) + (
        SettingSpec(
            GRAVITEE_REPO_PATH_KEY,
            "Путь к Gravitee Repository",
            "Общие",
            "path",
        ),
        SettingSpec(CERT_PATH_KEY, "Путь к сертификату", "Общие", "path"),
        SettingSpec(
            "AUTODEPLOY_PORT", "Порт веб-сервера", "Общие", "number", "8765",
            "Применится после перезапуска.", restart_required=True,
            minimum=1, maximum=65535,
        ),
        SettingSpec(
            "AUTODEPLOY_OPENCODE_AUTO_CONNECT", "Автоподключение OpenCode", "Общие",
            "boolean", "true", "Применится после перезапуска.", restart_required=True,
        ),
        SettingSpec(
            "AUTODEPLOY_OPEN_BROWSER", "Открывать браузер при старте", "Общие",
            "boolean", "true", "Применится после перезапуска.", restart_required=True,
        ),
        SettingSpec(
            "AUTODEPLOY_MAX_REQUEST_BYTES", "Максимальный размер API-запроса", "Общие",
            "number", str(2 * 1024 * 1024), "Применится после перезапуска.",
            restart_required=True, minimum=64 * 1024, maximum=100 * 1024 * 1024,
        ),
        SettingSpec(
            "AUTODEPLOY_MCP_ENABLED", "Встроенный MCP Server", "Общие",
            "boolean", "false",
            "Публикует инструменты AutoDeploy на /api/mcp и подключает их к Copilot.",
            restart_required=True,
        ),
        SettingSpec(
            OPENCODE_SERVER_URL_KEY, "Адрес сервера", "OpenCode", "text",
            DEFAULT_SERVER_URL, "Разрешён только localhost URL.",
        ),
        SettingSpec(
            OPENCODE_SERVER_USERNAME_KEY, "Basic Auth username", "OpenCode", "text",
            "opencode",
        ),
        SettingSpec(
            OPENCODE_SERVER_PASSWORD_KEY, "Basic Auth password", "OpenCode", "secret",
        ),
        SettingSpec(OPENCODE_PROVIDER_ID_KEY, "Provider ID", "OpenCode"),
        SettingSpec(OPENCODE_MODEL_ID_KEY, "Model ID", "OpenCode"),
        SettingSpec(
            OPENCODE_CONNECT_TIMEOUT_KEY, "Connect timeout, sec", "OpenCode", "number",
            "10", minimum=0.1, maximum=600,
        ),
        SettingSpec(
            OPENCODE_STARTUP_TIMEOUT_KEY, "Startup timeout, sec", "OpenCode", "number",
            "20", minimum=0.1, maximum=600,
        ),
        SettingSpec(
            OPENCODE_REQUEST_TIMEOUT_KEY, "Request timeout, sec", "OpenCode", "number",
            "120", minimum=0.1, maximum=3600,
        ),
        SettingSpec(
            OPENCODE_MAX_CONTEXT_CHARS_KEY, "Максимум символов контекста", "OpenCode",
            "number", "120000", minimum=10_000, maximum=500_000,
        ),
        SettingSpec(
            OPENCODE_REFERENCE_INLINE_MAX_ITEMS_KEY, "Inline-элементов справочника", "OpenCode",
            "number", "99", minimum=1, maximum=10_000,
        ),
        SettingSpec(
            OPENCODE_REFERENCE_INLINE_MAX_BYTES_KEY, "Размер одного inline-справочника", "OpenCode",
            "number", "24576", minimum=256, maximum=2 * 1024 * 1024,
        ),
        SettingSpec(
            OPENCODE_REFERENCE_INLINE_TOTAL_BYTES_KEY, "Общий размер inline-справочников", "OpenCode",
            "number", "49152", minimum=256, maximum=4 * 1024 * 1024,
        ),
        SettingSpec(
            OPENCODE_ALLOWED_MCP_KEY, "Разрешённые MCP", "OpenCode", "text", "",
            "Имена через запятую. Изменение применяется к новой AI-сессии.",
        ),
        SettingSpec(
            OPENCODE_REPOSITORY_MCP_KEY, "JSON Repository MCP", "OpenCode", "text", "",
            "Имя read-only MCP сервера.",
        ),
        SettingSpec(
            OPENCODE_REPOSITORY_GIT_PULL_KEY, "Разрешать запрос git pull", "OpenCode",
            "boolean", "true", "Каждый git pull всё равно требует подтверждения.",
        ),
        SettingSpec(
            SERVICE_PROVIDER_KEY, "Фабрика корпоративных сервисов", "Расширения", "text", "",
            "package.module:callable", restart_required=True,
        ),
        SettingSpec(
            FORM_REGISTRAR_KEY, "Регистратор корпоративных форм", "Расширения", "text", "",
            "package.module:callable", restart_required=True,
        ),
        SettingSpec(
            REFERENCE_HANDLER_FACTORY_KEY, "Фабрика справочников", "Расширения", "text", "",
            "package.module:callable", restart_required=True,
        ),
        SettingSpec(
            "AUTODEPLOY_UPDATE_MANIFEST_URL", "TFS manifest URL", "Обновления", "text", "",
            "HTTPS URL корпоративного update manifest.", restart_required=True,
        ),
        SettingSpec(
            "AUTODEPLOY_UPDATE_PROVIDER", "Фабрика update provider", "Обновления", "text", "",
            "package.module:callable", restart_required=True,
        ),
        SettingSpec(
            "AUTODEPLOY_UPDATE_TIMEOUT", "Update timeout, sec", "Обновления", "number", "30",
            restart_required=True, minimum=1, maximum=1800,
        ),
    )


SETTING_SPECS = _specs()
SETTING_BY_KEY = {item.key: item for item in SETTING_SPECS}
SECRET_KEYS = frozenset(item.key for item in SETTING_SPECS if item.kind == "secret")


def settings_snapshot(env_manager: EnvManager) -> dict[str, Any]:
    saved = env_manager.load()
    groups: list[dict[str, Any]] = []
    for group_name in dict.fromkeys(item.group for item in SETTING_SPECS):
        fields = []
        for spec in (item for item in SETTING_SPECS if item.group == group_name):
            raw = saved.get(spec.key, spec.default)
            document = asdict(spec)
            document["configured"] = bool(raw)
            document["value"] = None if spec.kind == "secret" else _public_value(spec, raw)
            fields.append(document)
        groups.append({"name": group_name, "fields": fields})
    return {"groups": groups}


def update_settings(
    env_manager: EnvManager,
    manager: OpenCodeManager,
    updates: Mapping[str, Any],
    clear: Iterable[str],
) -> dict[str, Any]:
    clear_keys = list(dict.fromkeys(str(key) for key in clear))
    if len(updates) + len(clear_keys) > len(SETTING_SPECS):
        raise ValueError("Слишком много настроек в одном запросе")
    unknown = sorted((set(updates) | set(clear_keys)) - set(SETTING_BY_KEY))
    if unknown:
        raise ValueError("Неизвестные настройки: " + ", ".join(unknown))
    non_secret_clear = sorted(set(clear_keys) - SECRET_KEYS)
    if non_secret_clear:
        raise ValueError("Явная очистка разрешена только для секретов")

    normalized: dict[str, str] = {}
    for key, value in updates.items():
        spec = SETTING_BY_KEY[key]
        normalized[key] = _normalize(spec, value)
    for key in clear_keys:
        normalized[key] = ""

    merged = env_manager.load()
    merged.update(normalized)
    _validate_relations(merged)
    env_manager.save(normalized)
    _configure_opencode(manager, merged)
    restart_required = any(
        SETTING_BY_KEY[key].restart_required for key in normalized
    )
    return {
        **settings_snapshot(env_manager),
        "saved_keys": sorted(normalized),
        "restart_required": restart_required,
        "reconnect_opencode": any(
            key.startswith("OPENCODE_SERVER_") or key == "AUTODEPLOY_MCP_ENABLED"
            for key in normalized
        ),
    }


def _public_value(spec: SettingSpec, raw: str) -> str | bool:
    if spec.kind == "boolean":
        return str(raw).strip().casefold() in {"1", "true", "yes", "on"}
    return str(raw)


def _normalize(spec: SettingSpec, value: Any) -> str:
    if spec.kind == "boolean":
        if isinstance(value, bool):
            return "true" if value else "false"
        lowered = str(value).strip().casefold()
        if lowered not in {"1", "0", "true", "false", "yes", "no", "on", "off"}:
            raise ValueError(f"{spec.label}: ожидается true/false")
        return "true" if lowered in {"1", "true", "yes", "on"} else "false"
    if value is None or isinstance(value, (dict, list)):
        raise ValueError(f"{spec.label}: ожидается строковое значение")
    text = str(value)
    if "\n" in text or "\r" in text or "\x00" in text:
        raise ValueError(f"{spec.label}: переносы строк запрещены")
    limit = 16_384 if spec.kind == "secret" else 4_096
    if len(text) > limit:
        raise ValueError(f"{spec.label}: значение слишком длинное")
    if spec.kind == "secret":
        if not text:
            raise ValueError(
                f"{spec.label}: пустое значение не меняет секрет; используйте явную очистку"
            )
        return text
    text = text.strip()
    if spec.required and not text:
        raise ValueError(f"{spec.label}: обязательное значение")
    if spec.kind == "number":
        try:
            number = float(text)
        except ValueError as exc:
            raise ValueError(f"{spec.label}: ожидается число") from exc
        if not math.isfinite(number):
            raise ValueError(f"{spec.label}: число должно быть конечным")
        if spec.minimum is not None and number < spec.minimum:
            raise ValueError(f"{spec.label}: минимум {spec.minimum:g}")
        if spec.maximum is not None and number > spec.maximum:
            raise ValueError(f"{spec.label}: максимум {spec.maximum:g}")
        return str(int(number)) if number.is_integer() else str(number)
    return text


def _validate_relations(values: Mapping[str, str]) -> None:
    provider = values.get(OPENCODE_PROVIDER_ID_KEY, "").strip()
    model = values.get(OPENCODE_MODEL_ID_KEY, "").strip()
    if bool(provider) != bool(model):
        raise ValueError("OpenCode Provider ID и Model ID задаются вместе")
    inline = int(values.get(OPENCODE_REFERENCE_INLINE_MAX_BYTES_KEY, "24576") or 24576)
    total = int(values.get(OPENCODE_REFERENCE_INLINE_TOTAL_BYTES_KEY, "49152") or 49152)
    if total < inline:
        raise ValueError("Общий размер inline-справочников не может быть меньше одного справочника")
    address = values.get(OPENCODE_SERVER_URL_KEY, DEFAULT_SERVER_URL).strip()
    parsed = urlsplit(address)
    if parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "localhost"}:
        raise ValueError("OpenCode Server URL должен указывать на http://127.0.0.1 или localhost")
    try:
        port = parsed.port
    except ValueError as exc:
        raise ValueError("Некорректный порт OpenCode Server") from exc
    if port is None:
        raise ValueError("В OpenCode Server URL необходимо указать порт")


def _configure_opencode(manager: OpenCodeManager, values: Mapping[str, str]) -> None:
    def number(key: str, default: float) -> float:
        return float(values.get(key, "") or default)

    manager.configure(
        server_url=values.get(OPENCODE_SERVER_URL_KEY, DEFAULT_SERVER_URL),
        connect_timeout=number(OPENCODE_CONNECT_TIMEOUT_KEY, 10),
        startup_timeout=number(OPENCODE_STARTUP_TIMEOUT_KEY, 20),
        request_timeout=number(OPENCODE_REQUEST_TIMEOUT_KEY, 120),
        username=values.get(OPENCODE_SERVER_USERNAME_KEY, "opencode"),
        password=values.get(OPENCODE_SERVER_PASSWORD_KEY, ""),
    )
