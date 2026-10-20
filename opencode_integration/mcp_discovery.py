"""Read MCP tool catalogs using the standard SDK; never invoke tools."""
from __future__ import annotations

import asyncio
import os
from datetime import timedelta
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.sse import sse_client
from mcp.client.stdio import stdio_client
from mcp.client.streamable_http import streamablehttp_client


async def _read(transport):
    async with transport as streams:
        async with ClientSession(streams[0], streams[1], read_timeout_seconds=timedelta(seconds=15)) as session:
            await session.initialize()
            tools, cursors, cursor = [], set(), None
            for _ in range(20):
                result = await session.list_tools(cursor=cursor)
                tools.extend({
                    "name": tool.name, "description": (tool.description or "")[:4000],
                    "input_schema": tool.inputSchema,
                } for tool in result.tools)
                cursor = result.nextCursor
                if not cursor:
                    return tools
                if cursor in cursors:
                    raise ValueError("MCP повторил cursor каталога")
                cursors.add(cursor)
            raise ValueError("Каталог MCP превышает лимит страниц")


async def _discover(config, directory):
    if config.get("type") == "local":
        command = config.get("command")
        if not isinstance(command, list) or not command:
            raise ValueError("MCP не содержит команды запуска")
        cwd = Path(config.get("cwd") or directory)
        if not cwd.is_absolute():
            cwd = Path(directory) / cwd
        parameters = StdioServerParameters(
            command=command[0], args=command[1:], cwd=str(cwd),
            env={**os.environ, **config.get("environment", {})},
        )
        with open(os.devnull, "w") as errlog:
            return await _read(stdio_client(parameters, errlog=errlog))
    if config.get("type") == "remote":
        url = config["url"]
        headers = config.get("headers") or {}
        if not url.rstrip("/").endswith("/sse"):
            try:
                return await _read(streamablehttp_client(url, headers=headers, timeout=15, sse_read_timeout=15))
            except Exception:
                # Some legacy SSE endpoints have no /sse suffix.
                pass
        return await _read(sse_client(url, headers=headers, timeout=15, sse_read_timeout=15))
    raise ValueError("Неизвестный transport MCP")


def discover_mcp_tools(config, directory):
    async def run():
        # Includes initialize, every tools/list page and transport shutdown.
        return await asyncio.wait_for(_discover(config, directory), timeout=25)
    return asyncio.run(run())
