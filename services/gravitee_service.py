"""
GraviteeService — работа с Gravitee API Management.
"""
from core.env_manager import EnvManager
from core.http_client import HttpClient


class GraviteeService:

    def __init__(self, env_manager: EnvManager, http_client: HttpClient) -> None:
        self._env_manager = env_manager
        self._http_client = http_client
