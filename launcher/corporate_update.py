"""Single replacement point for a corporate TFS delivery endpoint.

Corporate distributions normally set ``UPDATE_MANIFEST_URL`` here during their
pipeline. It may also be overridden with AUTODEPLOY_UPDATE_MANIFEST_URL in the
server-side .env. No value from this module is ever exposed to the web client.
"""
from __future__ import annotations

import base64


UPDATE_MANIFEST_URL = ""


def authorization_headers(tfs_token: str) -> dict[str, str]:
    if not tfs_token:
        return {}
    encoded = base64.b64encode(f":{tfs_token}".encode("utf-8")).decode("ascii")
    return {"Authorization": f"Basic {encoded}"}
