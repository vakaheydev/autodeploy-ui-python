from __future__ import annotations

import hashlib
import hmac
import importlib
import logging
import os
import ssl
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Callable, Protocol

from launcher.corporate_update import UPDATE_MANIFEST_URL, authorization_headers
from launcher.envfile import read_env
from launcher.manifest import ReleaseManifest
from launcher.paths import InstallPaths


_log = logging.getLogger("autodeploy.launcher.update")
Progress = Callable[[str, int, int | None], None]


class UpdateProvider(Protocol):
    def fetch_manifest(self) -> ReleaseManifest: ...
    def download(self, manifest: ReleaseManifest, destination: Path, progress: Progress | None = None) -> Path: ...


class _SafeRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Never forward a TFS Authorization header to a different host."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: ANN001
        redirected = super().redirect_request(req, fp, code, msg, headers, newurl)
        if redirected is None:
            return None
        old = urllib.parse.urlsplit(req.full_url)
        new = urllib.parse.urlsplit(newurl)
        if (old.scheme.casefold(), old.hostname, old.port) != (
            new.scheme.casefold(), new.hostname, new.port
        ):
            redirected.remove_header("Authorization")
            redirected.unredirected_hdrs.pop("Authorization", None)
        return redirected


class TfsUpdateProvider:
    """Read release manifest and immutable archive through TFS/HTTPS."""

    def __init__(
        self,
        manifest_url: str,
        token: str,
        *,
        timeout: float = 30.0,
        allow_insecure: bool = False,
    ) -> None:
        self.manifest_url = manifest_url.strip()
        self.headers = authorization_headers(token)
        self.timeout = max(1.0, min(float(timeout), 300.0))
        self.allow_insecure = allow_insecure
        context = ssl.create_default_context()
        self._opener = urllib.request.build_opener(
            _SafeRedirectHandler(), urllib.request.HTTPSHandler(context=context)
        )
        self._validate_url(self.manifest_url)

    def fetch_manifest(self) -> ReleaseManifest:
        _log.info("checking release manifest host=%s", self._safe_origin(self.manifest_url))
        request = urllib.request.Request(
            self.manifest_url,
            headers={**self.headers, "Accept": "application/json"},
            method="GET",
        )
        with self._opener.open(request, timeout=self.timeout) as response:
            payload = response.read(2 * 1024 * 1024 + 1)
        if len(payload) > 2 * 1024 * 1024:
            raise ValueError("Release manifest превышает 2 МБ")
        manifest = ReleaseManifest.parse(payload)
        self._validate_url(manifest.artifact_url)
        return manifest

    def download(
        self,
        manifest: ReleaseManifest,
        destination: Path,
        progress: Progress | None = None,
    ) -> Path:
        self._validate_url(manifest.artifact_url)
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary = destination.with_suffix(destination.suffix + ".part")
        request = urllib.request.Request(
            manifest.artifact_url,
            headers={**self.headers, "Accept": "application/zip, application/octet-stream"},
            method="GET",
        )
        digest = hashlib.sha256()
        received = 0
        _log.info(
            "downloading release version=%s host=%s",
            manifest.version,
            self._safe_origin(manifest.artifact_url),
        )
        try:
            with self._opener.open(request, timeout=self.timeout) as response, temporary.open("wb") as output:
                header_size = response.headers.get("Content-Length")
                total = int(header_size) if header_size and header_size.isdigit() else manifest.size
                if total is not None and total > 1024 * 1024 * 1024:
                    raise ValueError("Release artifact превышает 1 ГБ")
                while True:
                    chunk = response.read(1024 * 1024)
                    if not chunk:
                        break
                    received += len(chunk)
                    if received > 1024 * 1024 * 1024:
                        raise ValueError("Release artifact превышает 1 ГБ")
                    digest.update(chunk)
                    output.write(chunk)
                    if progress:
                        progress("Загрузка обновления", received, total)
            if manifest.size is not None and received != manifest.size:
                raise ValueError(
                    f"Размер artifact не совпал: ожидалось {manifest.size}, получено {received}"
                )
            if not hmac.compare_digest(digest.hexdigest(), manifest.sha256):
                raise ValueError("SHA-256 загруженного обновления не совпадает с manifest")
            os.replace(temporary, destination)
            return destination
        finally:
            if temporary.exists():
                temporary.unlink()

    def _validate_url(self, value: str) -> None:
        parsed = urllib.parse.urlsplit(value)
        local_http = parsed.scheme == "http" and parsed.hostname in {"127.0.0.1", "localhost"}
        if parsed.scheme != "https" and not local_http and not self.allow_insecure:
            raise ValueError("Update URL должен использовать HTTPS")
        if parsed.username or parsed.password:
            raise ValueError("Credentials запрещены внутри update URL")
        if not parsed.hostname:
            raise ValueError("Update URL не содержит host")

    @staticmethod
    def _safe_origin(value: str) -> str:
        parsed = urllib.parse.urlsplit(value)
        return f"{parsed.scheme}://{parsed.hostname or ''}{f':{parsed.port}' if parsed.port else ''}"


def load_update_provider(paths: InstallPaths) -> UpdateProvider:
    values = read_env(paths.env_file)
    custom = values.get("AUTODEPLOY_UPDATE_PROVIDER", "").strip()
    if custom:
        module_name, separator, attribute = custom.partition(":")
        if not separator:
            raise ValueError("AUTODEPLOY_UPDATE_PROVIDER должен иметь вид module:factory")
        factory = getattr(importlib.import_module(module_name), attribute)
        return factory(paths, values)
    manifest_url = values.get("AUTODEPLOY_UPDATE_MANIFEST_URL", "").strip() or UPDATE_MANIFEST_URL
    if not manifest_url:
        raise ValueError(
            "URL manifest не настроен в launcher/corporate_update.py или AUTODEPLOY_UPDATE_MANIFEST_URL"
        )
    try:
        timeout = float(values.get("AUTODEPLOY_UPDATE_TIMEOUT", "30") or 30)
    except ValueError:
        timeout = 30.0
    allow_insecure = values.get("AUTODEPLOY_ALLOW_INSECURE_UPDATE_URL", "").casefold() in {
        "1", "true", "yes", "on",
    }
    return TfsUpdateProvider(
        manifest_url,
        values.get("TFS_TOKEN", ""),
        timeout=timeout,
        allow_insecure=allow_insecure,
    )
