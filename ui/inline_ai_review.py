"""State model for reviewing AI field proposals directly in a form."""
from __future__ import annotations

import copy
from dataclasses import dataclass
from typing import Any, Iterable, Mapping

from opencode_integration.response_validator import PreviewField


PENDING = "pending"
ACCEPTED = "accepted"
REJECTED = "rejected"


@dataclass
class InlineReviewItem:
    field: PreviewField
    original_value: Any
    proposed_value: Any
    decision: str = PENDING


class InlineReviewState:
    """Tracks reversible field-level decisions independently from Tk widgets."""

    def __init__(
        self,
        preview_fields: Iterable[PreviewField],
        current_values: Mapping[str, Any],
    ) -> None:
        self._items: dict[str, InlineReviewItem] = {}
        for row in preview_fields:
            current = copy.deepcopy(current_values.get(row.key, row.current_value))
            proposed = copy.deepcopy(row.proposed_value)
            # ``null`` means "unknown", never an instruction to erase a field.
            if proposed is None or proposed == current:
                continue
            self._items[row.key] = InlineReviewItem(row, current, proposed)

    @property
    def items(self) -> tuple[InlineReviewItem, ...]:
        return tuple(self._items.values())

    @property
    def keys(self) -> tuple[str, ...]:
        return tuple(self._items)

    @property
    def pending_keys(self) -> tuple[str, ...]:
        return tuple(
            key for key, item in self._items.items() if item.decision == PENDING
        )

    @property
    def accepted_keys(self) -> tuple[str, ...]:
        return tuple(
            key for key, item in self._items.items() if item.decision == ACCEPTED
        )

    def get(self, key: str) -> InlineReviewItem:
        return self._items[key]

    def accept(self, key: str) -> Any:
        item = self.get(key)
        restore_proposal = item.decision == REJECTED
        item.decision = ACCEPTED
        return copy.deepcopy(item.proposed_value) if restore_proposal else None

    def reject(self, key: str) -> Any:
        item = self.get(key)
        item.decision = REJECTED
        return copy.deepcopy(item.original_value)

    def accept_all(self) -> dict[str, Any]:
        """Accept all, restoring proposals previously rejected by the operator."""
        patch: dict[str, Any] = {}
        for key, item in self._items.items():
            if item.decision == REJECTED:
                patch[key] = copy.deepcopy(item.proposed_value)
            item.decision = ACCEPTED
        return patch

    def reject_all(self) -> dict[str, Any]:
        patch: dict[str, Any] = {}
        for key, item in self._items.items():
            patch[key] = copy.deepcopy(item.original_value)
            item.decision = REJECTED
        return patch

    def originals(self) -> dict[str, Any]:
        return {
            key: copy.deepcopy(item.original_value)
            for key, item in self._items.items()
        }
