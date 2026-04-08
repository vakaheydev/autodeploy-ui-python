"""
Определения окружений (environments).
Каждое окружение имеет ключ для .env файла и отображаемое имя.
"""
from dataclasses import dataclass
from typing import List


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


TFS_TOKEN_KEY = "TFS_TOKEN"

ITSM_LOGIN_KEY  = "ITSM_LOGIN"
ITSM_PASSWORD_KEY = "ITSM_PASSWORD"
