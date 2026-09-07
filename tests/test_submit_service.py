from __future__ import annotations

import base64
from pathlib import Path
from typing import cast

from core.env_manager import EnvManager
from core.http_client import HttpClient
from forms.base_form import BaseForm
from services.submit_service import SubmitService


class _TfsAuthForm:
    def get_auth_type(self) -> str:
        return "tfs"


class _CaptureHttpClient:
    def __init__(self) -> None:
        self.basic_auth: tuple[str, str] | None = None
        self.bearer_token: str | None = None

    def set_basic_auth(self, login: str, password: str) -> None:
        self.basic_auth = (login, password)
        self.bearer_token = None

    def set_token(self, token: str) -> None:
        self.bearer_token = token
        self.basic_auth = None


def test_tfs_form_uses_empty_login_and_pat_as_basic_auth(tmp_path: Path) -> None:
    env = EnvManager(tmp_path / ".env")
    # LOGIN may be configured for unrelated corporate operations, but the TFS
    # PAT contract requires an empty Basic-auth username.
    env.save({"LOGIN": "domain\\user", "TFS_TOKEN": "private-pat"})
    client = _CaptureHttpClient()
    service = SubmitService(client, env)  # type: ignore[arg-type]

    service.set_auth(cast(BaseForm, _TfsAuthForm()), "test_int")

    assert client.basic_auth == ("", "private-pat")
    assert client.bearer_token is None


def test_empty_login_produces_tfs_pat_authorization_header() -> None:
    client = HttpClient()
    client.set_basic_auth("", "private-pat")

    request = client._build_request("https://tfs.example.invalid/api", "GET")

    encoded = base64.b64encode(b":private-pat").decode("ascii")
    assert request.get_header("Authorization") == f"Basic {encoded}"
