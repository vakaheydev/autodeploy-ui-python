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


class DraftSaveRequest(ValuesRequest):
    draft_id: str = Field(default="", max_length=200)
    clear_review: bool = False
    pending_review_fields: Optional[List[str]] = Field(default=None, max_length=100)


class TicketRequest(StrictModel):
    environment: str = Field(min_length=1, max_length=80)
    ticket_id: str = Field(min_length=1, max_length=200)


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


class ChatMessageRequest(StrictModel):
    message: str = Field(min_length=1, max_length=20_000)
    environment: str = Field(min_length=1, max_length=80)
    ticket_id: Optional[str] = Field(default=None, max_length=200)
    provider_id: str = Field(default="", max_length=200)
    model_id: str = Field(default="", max_length=300)
    thinking: str = Field(default="auto", max_length=100)


class PermissionReplyRequest(StrictModel):
    allow: bool


class SettingsUpdateRequest(StrictModel):
    values: Dict[str, Any] = Field(default_factory=dict, max_length=100)
    clear: List[str] = Field(default_factory=list, max_length=100)
