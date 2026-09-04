from __future__ import annotations

import json
import http.client
import os
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

import pytest


def free_port() -> int:
    with socket.socket() as value:
        value.bind(("127.0.0.1", 0))
        return int(value.getsockname()[1])


@pytest.fixture(scope="module")
def server(tmp_path_factory):
    runtime = tmp_path_factory.mktemp("server")
    port = free_port()
    environment = os.environ.copy()
    environment.update({
        "AUTODEPLOY_HOST": "127.0.0.1",
        "AUTODEPLOY_PORT": str(port),
        "AUTODEPLOY_OPEN_BROWSER": "false",
        "AUTODEPLOY_OPENCODE_AUTO_CONNECT": "false",
        "AUTODEPLOY_MCP_ENABLED": "true",
        "AUTODEPLOY_DATA_DIR": str(runtime / "data"),
        "AUTODEPLOY_ENV_FILE": str(runtime / ".env"),
        "AUTODEPLOY_LOG_DIR": str(runtime / "logs"),
    })
    process = subprocess.Popen(
        [sys.executable, "-m", "webapp"],
        cwd=Path(__file__).resolve().parents[2],
        env=environment,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    base = f"http://127.0.0.1:{port}"
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError("Server failed:\n" + (process.stdout.read() if process.stdout else ""))
        try:
            with urllib.request.urlopen(base + "/api/v1/health", timeout=0.5) as response:
                if response.status == 200:
                    break
        except OSError:
            time.sleep(0.1)
    else:
        process.terminate()
        raise TimeoutError("Server did not start")
    yield base
    process.terminate()
    try:
        process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait()


def request(base: str, path: str, *, method: str = "GET", body=None, headers=None):
    data = json.dumps(body).encode("utf-8") if body is not None else None
    request_headers = {"Accept": "application/json", **(headers or {})}
    if data is not None:
        request_headers["Content-Type"] = "application/json"
    value = urllib.request.Request(base + path, data=data, headers=request_headers, method=method)
    try:
        with urllib.request.urlopen(value, timeout=10) as response:
            content = response.read()
            return response.status, response.headers, content
    except urllib.error.HTTPError as exc:
        return exc.code, exc.headers, exc.read()


@pytest.mark.integration
def test_health_catalog_openapi_and_spa(server: str) -> None:
    status, headers, content = request(server, "/api/v1/health")
    assert status == 200
    assert json.loads(content)["service"] == "gravitee-autodeploy-web"
    assert headers["x-content-type-options"] == "nosniff"

    status, _, content = request(server, "/api/v1/catalog")
    catalog = json.loads(content)
    assert status == 200
    assert any(form["id"] == "api.create" for category in catalog["categories"] for form in category["forms"])
    assert request(server, "/api/openapi.json")[0] == 200
    status, headers, content = request(server, "/forms/api.create")
    assert status == 200
    assert "text/html" in headers["content-type"]
    assert b'<div id="root"></div>' in content


@pytest.mark.integration
def test_form_validation_contract(server: str) -> None:
    status, _, content = request(server, "/api/v1/forms/api.create?environment=test_int")
    document = json.loads(content)
    assert status == 200
    status, _, content = request(
        server,
        "/api/v1/forms/api.create/validate",
        method="POST",
        body={
            "environment": "test_int",
            "form_version": document["version"],
            "values": {
                "name": "Orders",
                "owner": "Team",
                "category": "internal",
                "context_path": "/orders",
                "endpoint_type": "rest",
            },
        },
    )
    validation = json.loads(content)
    assert status == 200
    assert validation["valid"] is True


@pytest.mark.integration
def test_browser_origin_and_request_limits(server: str) -> None:
    status, _, content = request(
        server, "/api/v1/health", headers={"Origin": "https://malicious.example"}
    )
    assert status == 403
    assert json.loads(content)["error"]["code"] == "origin_rejected"
    status, _, content = request(
        server,
        "/api/v1/forms/api.create/state",
        method="POST",
        body={},
        headers={"Content-Length": str(3 * 1024 * 1024)},
    )
    assert status == 413
    assert json.loads(content)["error"]["code"] == "request_too_large"

    # A client can omit Content-Length and stream chunked data.  The server
    # still stops reading at the configured hard limit instead of buffering it.
    parsed_port = int(server.rsplit(":", 1)[1])
    connection = http.client.HTTPConnection("127.0.0.1", parsed_port, timeout=10)
    try:
        connection.request(
            "POST",
            "/api/v1/forms/api.create/state",
            body=iter((b"x" * (1024 * 1024), b"y" * (1024 * 1024 + 1))),
            headers={"Content-Type": "application/json"},
            encode_chunked=True,
        )
        response = connection.getresponse()
        payload = json.loads(response.read())
        assert response.status == 413
        assert response.getheader("x-content-type-options") == "nosniff"
        assert payload["error"]["code"] == "request_too_large"
    finally:
        connection.close()


@pytest.mark.integration
def test_settings_keep_secrets_write_only(server: str) -> None:
    status, _, content = request(server, "/api/v1/settings")
    assert status == 200
    fields = [field for group in json.loads(content)["groups"] for field in group["fields"]]
    token = next(field for field in fields if field["key"] == "TFS_TOKEN")
    assert token["value"] is None

    status, _, content = request(
        server, "/api/v1/settings", method="PUT",
        body={"values": {"TFS_TOKEN": "integration-sensitive-token"}, "clear": []},
    )
    assert status == 200
    assert b"integration-sensitive-token" not in content
    updated = [field for group in json.loads(content)["groups"] for field in group["fields"]]
    assert next(field for field in updated if field["key"] == "TFS_TOKEN")["configured"] is True


@pytest.mark.integration
def test_streamable_http_mcp_lists_and_calls_documented_tools(server: str) -> None:
    status, _, content = request(
        server, "/api/mcp", method="POST",
        body={"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-03-26", "capabilities": {}, "clientInfo": {"name": "test", "version": "1"}}},
    )
    assert status == 200
    assert json.loads(content)["result"]["serverInfo"]["name"] == "gravitee-autodeploy"

    status, _, content = request(
        server, "/api/mcp", method="POST",
        body={"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
    )
    tools = json.loads(content)["result"]["tools"]
    assert {tool["name"] for tool in tools} >= {
        "search_forms",
        "semantic_search_forms",
        "get_form_schema",
        "prepare_form_draft",
        "research_repository",
        "preview_form_submission",
    }
    assert all(tool["annotations"]["destructiveHint"] is False for tool in tools)
    assert next(
        tool for tool in tools if tool["name"] == "prepare_form_draft"
    )["annotations"] == {
        "readOnlyHint": False,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    }

    status, _, content = request(
        server, "/api/mcp", method="POST",
        body={"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": "search_forms", "arguments": {"query": "создание api"}}},
    )
    result = json.loads(content)["result"]
    assert result["isError"] is False
    assert any(item["id"] == "api.create" for item in result["structuredContent"]["items"])
