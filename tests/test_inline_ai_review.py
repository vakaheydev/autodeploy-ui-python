from __future__ import annotations

import unittest

from forms.fields import FieldType
from opencode_integration.response_validator import PreviewField
from ui.inline_ai_review import ACCEPTED, PENDING, REJECTED, InlineReviewState


def _field(
    key: str,
    current: object,
    proposed: object,
) -> PreviewField:
    return PreviewField(
        key=key,
        label=key,
        field_type=FieldType.TEXT,
        current_value=current,
        proposed_value=proposed,
        confidence="high",
        source="operator",
        reason="test",
    )


class InlineReviewStateTests(unittest.TestCase):
    def test_only_real_non_null_changes_require_review(self) -> None:
        state = InlineReviewState(
            (
                _field("changed", "old", "new"),
                _field("same", "same", "same"),
                _field("unknown", "keep", None),
            ),
            {"changed": "actual", "same": "same", "unknown": "keep"},
        )

        self.assertEqual(state.keys, ("changed",))
        self.assertEqual(state.pending_keys, ("changed",))
        self.assertEqual(state.get("changed").original_value, "actual")

    def test_reject_is_reversible_and_accept_restores_ai_proposal(self) -> None:
        state = InlineReviewState(
            (_field("path", "/old", "/new"),),
            {"path": "/old"},
        )

        self.assertEqual(state.reject("path"), "/old")
        self.assertEqual(state.get("path").decision, REJECTED)
        self.assertEqual(state.accept("path"), "/new")
        self.assertEqual(state.get("path").decision, ACCEPTED)
        self.assertEqual(state.pending_keys, ())

    def test_accepting_visible_proposal_does_not_overwrite_manual_edit(self) -> None:
        state = InlineReviewState(
            (_field("name", "Old", "AI name"),),
            {"name": "Old"},
        )

        self.assertIsNone(state.accept("name"))
        self.assertEqual(state.get("name").decision, ACCEPTED)

    def test_bulk_actions_return_only_values_that_need_widget_updates(self) -> None:
        state = InlineReviewState(
            (
                _field("one", "old-1", "new-1"),
                _field("two", "old-2", "new-2"),
            ),
            {"one": "old-1", "two": "old-2"},
        )
        state.accept("one")
        state.reject("two")

        self.assertEqual(state.accept_all(), {"two": "new-2"})
        self.assertEqual(state.accepted_keys, ("one", "two"))
        self.assertEqual(
            state.reject_all(),
            {"one": "old-1", "two": "old-2"},
        )
        self.assertTrue(all(item.decision == REJECTED for item in state.items))

    def test_mutable_values_are_snapshotted(self) -> None:
        current = ["old"]
        proposed = ["new"]
        state = InlineReviewState(
            (_field("multi", current, proposed),),
            {"multi": current},
        )
        current.append("mutated")
        proposed.append("mutated")

        self.assertEqual(state.originals(), {"multi": ["old"]})
        self.assertEqual(state.get("multi").proposed_value, ["new"])
        self.assertEqual(state.get("multi").decision, PENDING)


if __name__ == "__main__":
    unittest.main()
