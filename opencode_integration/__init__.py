"""Безопасная интеграция AutoDeploy UI с локальным OpenCode Server."""

from opencode_integration.agent import FormExtractorAgent
from opencode_integration.client import OpenCodeClient
from opencode_integration.data_sources import AzureDevOpsDataSource, ITSMDataSource
from opencode_integration.manager import OpenCodeManager
from opencode_integration.reference_resolver import LocalReferenceResolver

__all__ = [
    "AzureDevOpsDataSource",
    "FormExtractorAgent",
    "ITSMDataSource",
    "LocalReferenceResolver",
    "OpenCodeClient",
    "OpenCodeManager",
]
