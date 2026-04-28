"""
TfsService — работа с TFS / Azure DevOps.
"""
from core.env_manager import EnvManager
from core.http_client import HttpClient


class TfsService:

    def __init__(self, env_manager: EnvManager, http_client: HttpClient) -> None:
        self._env_manager = env_manager
        self._http_client = http_client
