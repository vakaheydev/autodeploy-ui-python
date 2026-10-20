"""Read-only protocol negotiation for OpenCode 1.x and 2.x servers."""
from __future__ import annotations

import threading
import time

from .client import OpenCodeClient, OpenCodeError, OpenCodeHttpError, OpenCodeProtocolError
from .client_v2 import OpenCodeV2Client


class OpenCodeConnection:
    """Select one adapter before any session/configuration mutation.

    V1 may serve its Web UI (HTTP 200 HTML) at an unknown /api/info route.
    Only that response or a missing route permits fallback. A custom V1 login
    may authenticate a read-only route probe after V2's fixed login is rejected;
    HTTP 401 alone never selects a protocol.
    """

    def __init__(self, base_url, timeout=120.0, **kwargs):
        self._v1 = OpenCodeClient(base_url, timeout, **kwargs)
        self._v2 = OpenCodeV2Client(base_url, timeout, **kwargs)
        self._custom_v1_credentials = self._v1.username != "opencode" and bool(kwargs.get("password"))
        self._adapter = None
        self._lock = threading.RLock()

    @property
    def timeout(self):
        return self._v1.timeout

    @timeout.setter
    def timeout(self, value):
        self._v1.timeout = value
        self._v2.timeout = value

    @property
    def base_url(self):
        return self._v1.base_url

    @property
    def directory(self):
        return self._v1.directory

    def health(self, timeout=None):
        with self._lock:
            if self._adapter is not None:
                return self._adapter.health(timeout=timeout)
            deadline = time.monotonic() + (self.timeout if timeout is None else timeout)
            try:
                health = self._v2.health(timeout=timeout)
            except OpenCodeHttpError as exc:
                if exc.status == 401 and self._custom_v1_credentials:
                    # V1 can guard even unknown routes using a custom username.
                    # Probe the SAME route with those credentials: only a missing
                    # V2 route/HTML permits selecting V1, never another 401.
                    self._require_missing_v2_route(deadline)
                elif exc.status not in {404, 405}:
                    raise
            except OpenCodeProtocolError:
                pass
            else:
                self._adapter = self._v2
                return health
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise OpenCodeError("Истёк timeout определения версии OpenCode")
            health = self._v1.health(timeout=remaining)
            if not health.version.removeprefix("v").startswith("1."):
                raise OpenCodeError("Неподдерживаемая версия OpenCode; требуется 1.x или 2.x")
            self._adapter = self._v1
            return health

    def _require_missing_v2_route(self, deadline):
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise OpenCodeError("Истёк timeout определения версии OpenCode")
        try:
            self._v1._request("GET", "/api/info", timeout=remaining, instance=False)
        except OpenCodeHttpError as exc:
            if exc.status not in {404, 405}:
                raise
        except OpenCodeProtocolError:
            pass
        else:
            raise OpenCodeError("Не удалось определить протокол OpenCode с сохранённым логином")

    def __getattr__(self, name):
        # Existing callers continue to use the stable Python client interface.
        if name.startswith("_"):
            raise AttributeError(name)
        with self._lock:
            if self._adapter is None:
                self.health()
            return getattr(self._adapter, name)
