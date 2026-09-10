from __future__ import annotations

from pathlib import Path

import pytest

from webapp.itsm_prompt_settings import ITSMPromptSettingsStore


def test_prompt_rules_round_trip_and_match_ticket_type_case_insensitively(
    tmp_path: Path,
) -> None:
    store = ITSMPromptSettingsStore(tmp_path / "itsm-ai-prompts.json")

    snapshot = store.update([
        {
            "ticket_type": " Create_API_V2 ",
            "prompt": "Первая строка\r\nВторая строка",
        }
    ])

    assert snapshot["warning"] == ""
    assert snapshot["rules"] == [{
        "ticket_type": "Create_API_V2",
        "prompt": "Первая строка\nВторая строка",
    }]
    assert store.prompt_for("create_api_v2") == "Первая строка\nВторая строка"
    assert store.prompt_for("another_type") is None


def test_prompt_rules_reject_duplicate_normalized_ticket_types(tmp_path: Path) -> None:
    store = ITSMPromptSettingsStore(tmp_path / "itsm-ai-prompts.json")

    with pytest.raises(ValueError, match="больше одного раза"):
        store.update([
            {"ticket_type": "enable_ingress", "prompt": "one"},
            {"ticket_type": " ENABLE_INGRESS ", "prompt": "two"},
        ])


def test_corrupt_prompt_file_is_visible_but_does_not_break_ai_fallback(
    tmp_path: Path,
) -> None:
    path = tmp_path / "itsm-ai-prompts.json"
    path.write_text("not-json", encoding="utf-8")
    store = ITSMPromptSettingsStore(path)

    assert store.snapshot()["warning"]
    assert store.prompt_for("create_api") is None
