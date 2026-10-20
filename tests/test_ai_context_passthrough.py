"""AI payloads preserve operator-approved content, including tool details."""
import json

import pytest

from forms.fields import ReferenceConfig
from opencode_integration.agent import FormExtractorAgent
from opencode_integration.context_builder import (
    MAX_COLLECTION_ITEMS, MAX_DEPTH, MAX_STRING_CHARS, redact_text, sanitize,
)
from opencode_integration.copilot import UnifiedCopilot
from webapp.ai_service import WebAIService
from webapp.form_runtime import _public_item


@pytest.mark.parametrize("text", [
    "contextPath=/payments/v2 path=/apis/catalog compatibility=enabled",
    '{"tokenCount":123456,"authorizationType":"oauth2","accessTokenTtl":3600}',
    '{"password":"example-password","token":"example-token","client_secret":"example-value"}',
    "Authorization: Bearer example-token-value",
    "Basic ZXhhbXBsZTpwYXNzd29yZA==",
    "eyJhbGciOiJub25lIn0.eyJleGFtcGxlIjp0cnVlfQ.example-signature",
    "-----BEGIN PRIVATE KEY-----\nEXAMPLE-ONLY\n-----END PRIVATE KEY-----",
])
def test_ai_text_does_not_invent_redaction_markers(text):
    assert redact_text(text) == text
    assert sanitize({"body": text}) == {"body": text}


@pytest.mark.parametrize("formatter", [
    FormExtractorAgent._safe_detail, UnifiedCopilot._safe_detail, WebAIService._safe_detail,
])
def test_tool_inputs_and_outputs_keep_original_fields(formatter):
    payload = {
        "contextPath": "/payments/v2",
        "token": "example-token",
        "headers": {"Authorization": "Bearer example-value"},
        "rawResponse": {"password": "example-password"},
    }
    assert sanitize(payload) == payload
    assert json.loads(formatter(payload)) == payload


def test_context_normalization_and_limits_are_still_enforced():
    assert sanitize({"body": "line\r\nnext\x00", "number": float("inf")}) == {
        "body": "line\nnext", "number": None,
    }
    assert sanitize("x" * (MAX_STRING_CHARS + 1)).endswith("[TRUNCATED]")
    assert sanitize(list(range(MAX_COLLECTION_ITEMS + 1)))[-1] == {"_truncated_items": 1}
    assert sanitize({"nested": "value"}, depth=MAX_DEPTH) == "[TRUNCATED_MAX_DEPTH]"


def test_declared_reference_fields_are_not_filtered_by_their_names():
    reference = ReferenceConfig(
        source="example", resource="examples", value_key="token", label_key="name",
        detail_keys=("authorizationType", "password"),
    )
    row = {"token": "example-id", "name": "Example", "authorizationType": "oauth2",
           "password": "example-value", "other_field": "not-declared"}
    assert _public_item(row, reference) == {
        key: value for key, value in row.items() if key != "other_field"
    }
