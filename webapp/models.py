"""Public versioned HTTP contracts."""
from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ValuesRequest(StrictModel):
    environment: str = Field(min_length=1, max_length=80)
    values: Dict[str, Any] = Field(default_factory=dict)
    form_version: str = Field(default="", max_length=128)


class ReferenceRequest(StrictModel):
    environment: str = Field(min_length=1, max_length=80)
    values: Dict[str, Any] = Field(default_factory=dict)
    query: str = Field(default="", max_length=500)
    offset: int = Field(default=0, ge=0, le=1_000_000)
    limit: int = Field(default=100, ge=1, le=500)
    refresh: bool = False


class SubmitRequest(ValuesRequest):
    confirmation_token: str = Field(default="", max_length=300)
    draft_id: str = Field(default="", max_length=200)


class ActionRequest(ValuesRequest):
    confirmation_token: str = Field(default="", max_length=300)


class ActionDialogOpenRequest(StrictModel):
    environment: str = Field(min_length=1, max_length=80)
    form_values: Dict[str, Any] = Field(default_factory=dict)
    form_version: str = Field(default="", max_length=128)


class ActionDialogStateRequest(ActionDialogOpenRequest):
    dialog_values: Dict[str, Any] = Field(default_factory=dict)


class ActionDialogReferenceRequest(ActionDialogStateRequest):
    query: str = Field(default="", max_length=500)
    offset: int = Field(default=0, ge=0, le=1_000_000)
    limit: int = Field(default=100, ge=1, le=500)
    refresh: bool = False


class ActionDialogExecuteRequest(ActionDialogStateRequest):
    confirmation_token: str = Field(default="", max_length=300)


class DraftSaveRequest(ValuesRequest):
    draft_id: str = Field(default="", max_length=200)
    clear_review: bool = False
    pending_review_fields: Optional[List[str]] = Field(default=None, max_length=100)


class TicketRequest(StrictModel):
    environment: str = Field(min_length=1, max_length=80)
    ticket_id: str = Field(min_length=1, max_length=200)
    values: Dict[str, Any] = Field(default_factory=dict)
    form_version: str = Field(default="", max_length=128)


class SearchRequest(StrictModel):
    kind: Literal["api", "application"]
    environments: List[str] = Field(min_length=1, max_length=6)
    query: str = Field(min_length=1, max_length=500)
    limit: int = Field(default=100, ge=1, le=500)
    refresh: bool = False

    @field_validator("environments")
    @classmethod
    def unique_environments(cls, value: List[str]) -> List[str]:
        return list(dict.fromkeys(value))


class SearchStatusRequest(StrictModel):
    kind: Literal["api", "application"]
    environments: List[str] = Field(min_length=1, max_length=6)

    @field_validator("environments")
    @classmethod
    def unique_environments(cls, value: List[str]) -> List[str]:
        return list(dict.fromkeys(value))


class EnvironmentActivationRequest(StrictModel):
    environment: str = Field(min_length=1, max_length=80)
    previous_environment: Optional[str] = Field(default=None, max_length=80)


class ErrorItem(StrictModel):
    field: Optional[str] = None
    code: str
    message: str


class ValidationResponse(StrictModel):
    valid: bool
    values: Dict[str, Any]
    errors: List[ErrorItem]
    visible_fields: List[str]


class ChatSessionRequest(StrictModel):
    environment: str = Field(default="test_int", min_length=1, max_length=80)


class ChatSessionUpdateRequest(StrictModel):
    title: str = Field(min_length=1, max_length=80)


class ChatReferenceMention(StrictModel):
    catalog_id: str = Field(min_length=1, max_length=40, pattern=r"^[a-f0-9]+$")
    cache_resource: str = Field(min_length=1, max_length=500)
    identifier: str = Field(min_length=1, max_length=1_000)


class ChatReferenceSearchRequest(StrictModel):
    environment: str = Field(min_length=1, max_length=80)
    query: str = Field(default="", max_length=500)
    limit: int = Field(default=20, ge=1, le=50)


class ChatMessageRequest(StrictModel):
    message: str = Field(min_length=1, max_length=20_000)
    environment: str = Field(min_length=1, max_length=80)
    ticket_id: Optional[str] = Field(default=None, max_length=200)
    provider_id: str = Field(default="", max_length=200)
    model_id: str = Field(default="", max_length=300)
    thinking: str = Field(default="auto", max_length=100)
    mentions: List[ChatReferenceMention] = Field(default_factory=list, max_length=20)


class PermissionReplyRequest(StrictModel):
    allow: bool


class SettingsUpdateRequest(StrictModel):
    values: Dict[str, Any] = Field(default_factory=dict, max_length=100)
    clear: List[str] = Field(default_factory=list, max_length=100)


class PluginValuesRequest(StrictModel):
    environment: str = Field(min_length=1, max_length=80)
    values: Dict[str, Any] = Field(default_factory=dict)
    plugin_version: str = Field(default="", max_length=128)


class PluginActionRequest(PluginValuesRequest):
    confirmation_token: str = Field(default="", max_length=300)


class PluginAIPolicyItem(StrictModel):
    id: str = Field(min_length=1, max_length=80)
    visible: bool
    operations: Dict[str, Literal["deny", "allow", "manual"]] = Field(
        default_factory=dict, max_length=200
    )


class PluginAIPolicyUpdateRequest(StrictModel):
    ai_visible: bool
    plugins: List[PluginAIPolicyItem] = Field(default_factory=list, max_length=200)
