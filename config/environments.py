"""
Определения окружений (environments).
Каждое окружение имеет ключ для .env файла и отображаемое имя.
"""
from dataclasses import dataclass
from typing import List, Tuple


@dataclass(frozen=True)
class Environment:
    key: str          # используется как суффикс в .env: GRAVITEE_TOKEN_<KEY>
    label: str        # отображается в UI


# Полный список окружений. Порядок определяет порядок в UI.
ENVIRONMENTS: List[Environment] = [
    Environment("test_int",     "Test Internal"),
    Environment("test_ext",     "Test External"),
    Environment("regress_int",  "Regress Internal"),
    Environment("regress_ext",  "Regress External"),
    Environment("prod_int",     "Prod Internal"),
    Environment("prod_ext",     "Prod External"),
]

# Быстрый доступ по ключу
ENVIRONMENT_MAP = {env.key: env for env in ENVIRONMENTS}


def gravitee_token_key(env_key: str) -> str:
    """Возвращает ключ GRAVITEE токена для .env файла."""
    return f"GRAVITEE_TOKEN_{env_key.upper()}"


LOGIN_KEY     = "LOGIN"
TFS_TOKEN_KEY = "TFS_TOKEN"

ITSM_LOGIN_KEY    = "ITSM_LOGIN"
ITSM_PASSWORD_KEY = "ITSM_PASSWORD"

GRAVITEE_REPO_PATH_KEY = "GRAVITEE_REPO_PATH"

CERT_PATH_KEY = "CERT_PATH"

# OpenCode хранит provider credentials в собственной конфигурации. Здесь
# находятся параметры локального клиента и, при необходимости, Basic Auth
# password самого localhost-сервера; он никогда не передаётся AI-модели.
OPENCODE_PROVIDER_ID_KEY = "OPENCODE_PROVIDER_ID"
OPENCODE_MODEL_ID_KEY = "OPENCODE_MODEL_ID"
OPENCODE_SERVER_URL_KEY = "OPENCODE_SERVER_URL"
OPENCODE_SERVER_USERNAME_KEY = "OPENCODE_SERVER_USERNAME"
OPENCODE_SERVER_PASSWORD_KEY = "OPENCODE_SERVER_PASSWORD"
OPENCODE_CONNECT_TIMEOUT_KEY = "OPENCODE_CONNECT_TIMEOUT"
OPENCODE_STARTUP_TIMEOUT_KEY = "OPENCODE_STARTUP_TIMEOUT"
OPENCODE_REQUEST_TIMEOUT_KEY = "OPENCODE_REQUEST_TIMEOUT"
OPENCODE_MAX_CONTEXT_CHARS_KEY = "OPENCODE_MAX_CONTEXT_CHARS"
OPENCODE_REFERENCE_INLINE_MAX_ITEMS_KEY = "OPENCODE_REFERENCE_INLINE_MAX_ITEMS"
OPENCODE_REFERENCE_INLINE_MAX_BYTES_KEY = "OPENCODE_REFERENCE_INLINE_MAX_BYTES"
OPENCODE_REFERENCE_INLINE_TOTAL_BYTES_KEY = "OPENCODE_REFERENCE_INLINE_TOTAL_BYTES"
OPENCODE_ALLOWED_MCP_KEY = "OPENCODE_ALLOWED_MCP"
OPENCODE_REPOSITORY_MCP_KEY = "OPENCODE_REPOSITORY_MCP"
OPENCODE_REPOSITORY_GIT_PULL_KEY = "OPENCODE_REPOSITORY_GIT_PULL"

# Обязательные поля настроек. Проверяются при каждом запуске.
# Формат: (ключ .env, отображаемое название для пользователя)
# Добавьте сюда любые поля, без которых приложение не может работать.
REQUIRED_SETTINGS: List[Tuple[str, str]] = [
    (LOGIN_KEY, "Логин"),
]
