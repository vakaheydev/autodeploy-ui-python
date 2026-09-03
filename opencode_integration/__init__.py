"""Безопасная интеграция AutoDeploy UI с локальным OpenCode Server."""

from opencode_integration.agent import FormExtractorAgent
from opencode_integration.client import OpenCodeClient
from opencode_integration.manager import OpenCodeManager

__all__ = ["FormExtractorAgent", "OpenCodeClient", "OpenCodeManager"]
