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
ITSM_TICKET_URL_TEMPLATE_KEY = "ITSM_TICKET_URL_TEMPLATE"

ADO_PR_URL_TEMPLATE_KEY = "ADO_PR_URL_TEMPLATE"
ADO_ALLOWED_HOSTS_KEY = "ADO_ALLOWED_HOSTS"

GRAVITEE_REPO_PATH_KEY = "GRAVITEE_REPO_PATH"

CERT_PATH_KEY = "CERT_PATH"

# OpenCode хранит provider credentials в собственной конфигурации. Здесь только
# несекретные параметры выбора модели и ограничения локального клиента.
OPENCODE_PROVIDER_ID_KEY = "OPENCODE_PROVIDER_ID"
OPENCODE_MODEL_ID_KEY = "OPENCODE_MODEL_ID"
OPENCODE_STARTUP_TIMEOUT_KEY = "OPENCODE_STARTUP_TIMEOUT"
OPENCODE_REQUEST_TIMEOUT_KEY = "OPENCODE_REQUEST_TIMEOUT"
OPENCODE_MAX_CONTEXT_CHARS_KEY = "OPENCODE_MAX_CONTEXT_CHARS"

# Обязательные поля настроек. Проверяются при каждом запуске.
# Формат: (ключ .env, отображаемое название для пользователя)
# Добавьте сюда любые поля, без которых приложение не может работать.
REQUIRED_SETTINGS: List[Tuple[str, str]] = [
    (LOGIN_KEY, "Логин"),
]
