"""TfsService — безопасное получение PR, comments и списка changes из ADO."""
from __future__ import annotations

import re
import urllib.parse
from typing import Any, Dict, Optional

from config.environments import (
    ADO_ALLOWED_HOSTS_KEY,
    ADO_PR_URL_TEMPLATE_KEY,
    TFS_TOKEN_KEY,
)
from core.env_manager import EnvManager
from core.http_client import HttpClient

_UI_PR_RE = re.compile(
    r"^(?P<base>https?://[^/]+)(?P<prefix>/[^?#]+?)/_git/"
    r"(?P<repo>[^/?#]+)/pullrequest/(?P<id>\d+)",
    re.IGNORECASE,
)
_API_PR_RE = re.compile(
    r"^(?P<repo_api>https?://.+?/_apis/git/repositories/[^/?#]+)"
    r"/pullrequests?/(?P<id>\d+)(?:[?#].*)?$",
    re.IGNORECASE,
)


class TfsService:

    def __init__(self, env_manager: EnvManager, http_client: HttpClient) -> None:
        self._env_manager = env_manager
        self._http_client = http_client

    def get_pull_request(self, reference: Any, environment: str = "") -> Dict[str, Any]:
        """Получает связанный PR. `reference` приходит из недоверенной ITSM-заявки."""
        if isinstance(reference, dict):
            embedded = reference.get("pull_request") or reference.get("pullRequest")
            if isinstance(embedded, dict):
                reference = embedded
            for key in ("url", "remoteUrl", "pullRequestUrl", "pull_request_url"):
                if isinstance(reference, dict) and reference.get(key):
                    reference = reference[key]
                    break
            else:
                # Полный встроенный объект PR уже пригоден как контекст и не требует сети.
                return {"pull_request": reference, "threads": [], "changes": []}

        settings = self._env_manager.load()
        url = self._resolve_url(reference, environment, settings)
        self._validate_allowed_url(url, settings)
        token = settings.get(TFS_TOKEN_KEY, "")
        if not token:
            raise RuntimeError("Не настроен TFS_TOKEN для Azure DevOps")

        client = HttpClient(
            timeout=30,
            allow_redirects=False,
            max_response_bytes=10 * 1024 * 1024,
        )
        client.set_token(token)
        detail = client.get(url)
        if not isinstance(detail, dict):
            raise RuntimeError("Azure DevOps вернул неожиданный формат PR")

        pr_id = detail.get("pullRequestId") or self._id_from_url(url)
        repo_api = self._repo_api(detail, url)
        threads: Any = []
        changes: Any = []
        related_errors: list[str] = []
        if pr_id and repo_api:
            self._validate_allowed_url(repo_api, settings)
            pr_api = f"{repo_api.rstrip('/')}/pullRequests/{urllib.parse.quote(str(pr_id), safe='')}"
            try:
                thread_response = client.get(
                    f"{pr_api}/threads?api-version=7.1&$top=100"
                )
                threads = self._items(thread_response)
            except Exception as exc:
                related_errors.append(f"threads:{type(exc).__name__}")
            try:
                iterations_response = client.get(f"{pr_api}/iterations?api-version=7.1")
                iterations = self._items(iterations_response)
                if iterations:
                    iteration_id = iterations[-1].get("id")
                    if iteration_id is not None:
                        changes_response = client.get(
                            f"{pr_api}/iterations/"
                            f"{urllib.parse.quote(str(iteration_id), safe='')}/changes"
                            "?api-version=7.1&$top=200"
                        )
                        changes = self._items(changes_response)
            except Exception as exc:
                related_errors.append(f"changes:{type(exc).__name__}")

        return {
            "pull_request": detail,
            "threads": threads,
            "changes": changes,
            "collection_warnings": related_errors,
        }

    def _resolve_url(
        self,
        reference: Any,
        environment: str,
        settings: dict[str, str],
    ) -> str:
        text = str(reference).strip()
        if not text:
            raise ValueError("Пустая ссылка на Azure DevOps PR")
        if text.isdigit():
            template = self._setting_for_environment(
                settings, ADO_PR_URL_TEMPLATE_KEY, environment
            )
            if not template:
                raise RuntimeError(
                    "В заявке указан только PR ID, но не настроен ADO_PR_URL_TEMPLATE"
                )
            if "{pull_request_id}" not in template:
                raise RuntimeError("ADO_PR_URL_TEMPLATE должен содержать {pull_request_id}")
            try:
                text = template.format(
                    pull_request_id=urllib.parse.quote(text, safe=""),
                    environment=urllib.parse.quote(environment, safe="-_"),
                )
            except (KeyError, ValueError) as exc:
                raise RuntimeError(f"Некорректный ADO PR URL-шаблон: {exc}") from exc

        ui_match = _UI_PR_RE.match(text)
        if ui_match:
            prefix = ui_match.group("prefix")
            repo = urllib.parse.quote(urllib.parse.unquote(ui_match.group("repo")), safe="")
            pr_id = ui_match.group("id")
            return (
                f"{ui_match.group('base')}{prefix}/_apis/git/repositories/{repo}/"
                f"pullRequests/{pr_id}?api-version=7.1"
            )
        if _API_PR_RE.match(text):
            return self._with_api_version(text)
        raise RuntimeError("Не удалось распознать URL Azure DevOps pull request")

    def _validate_allowed_url(self, url: str, settings: dict[str, str]) -> None:
        parsed = urllib.parse.urlparse(url)
        if (
            parsed.scheme != "https"
            or not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
        ):
            raise RuntimeError("ADO URL должен быть HTTPS-адресом без credentials")
        host = parsed.hostname.lower()
        allowed = {"dev.azure.com"}
        configured = settings.get(ADO_ALLOWED_HOSTS_KEY, "")
        allowed.update(item.strip().lower() for item in configured.split(",") if item.strip())
        template = settings.get(ADO_PR_URL_TEMPLATE_KEY, "")
        if template:
            template_host = urllib.parse.urlparse(template).hostname
            if template_host:
                allowed.add(template_host.lower())
        if not (host in allowed or host.endswith(".visualstudio.com")):
            raise RuntimeError(
                f"ADO host {host!r} отсутствует в ADO_ALLOWED_HOSTS"
            )

    @staticmethod
    def _repo_api(detail: Dict[str, Any], request_url: str) -> Optional[str]:
        repository = detail.get("repository")
        if isinstance(repository, dict) and repository.get("url"):
            return str(repository["url"])
        match = _API_PR_RE.match(request_url)
        return match.group("repo_api") if match else None

    @staticmethod
    def _id_from_url(url: str) -> Optional[str]:
        match = _API_PR_RE.match(url)
        return match.group("id") if match else None

    @staticmethod
    def _items(payload: Any) -> list[Dict[str, Any]]:
        if isinstance(payload, list):
            return [item for item in payload if isinstance(item, dict)]
        if isinstance(payload, dict):
            value = payload.get("value", payload.get("items", []))
            if isinstance(value, list):
                return [item for item in value if isinstance(item, dict)]
        return []

    @staticmethod
    def _with_api_version(url: str) -> str:
        parsed = urllib.parse.urlparse(url)
        query = urllib.parse.parse_qsl(parsed.query, keep_blank_values=True)
        if not any(key.lower() == "api-version" for key, _ in query):
            query.append(("api-version", "7.1"))
        return urllib.parse.urlunparse(parsed._replace(query=urllib.parse.urlencode(query)))

    @staticmethod
    def _setting_for_environment(settings: dict[str, str], key: str, environment: str) -> str:
        env_key = f"{key}_{environment.upper()}" if environment else ""
        return settings.get(env_key, "") or settings.get(key, "")
