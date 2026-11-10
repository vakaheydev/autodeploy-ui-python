"""Portable Python-owned field buttons for desktop and web clients."""
from __future__ import annotations

import copy
from dataclasses import dataclass, field
from typing import Any, Callable, Mapping, Sequence, TYPE_CHECKING

if TYPE_CHECKING:
    from core.http_client import HttpClient
    from forms.fields import FieldDefinition, ReferenceConfig


@dataclass
class FieldActionContext:
    """Request-scoped capabilities; never serialized to the browser.

    ``form_values`` and ``dialog_values`` are normalized snapshots. Use
    ``set_value`` to update exactly the owning field, including a repeated or
    nested instance. Changes reach the browser only after a successful handler.
    ``services`` exposes the installed provider's itsm/tfs/gravitee services.
    """

    environment: str
    field_path: str
    field: FieldDefinition
    value: Any
    form_values: dict[str, Any]
    dialog_values: dict[str, Any]
    http: HttpClient
    services: Any
    _load_reference: Callable[..., list[dict[str, Any]]] = field(repr=False)
    _selected_items: Callable[[str], list[dict[str, Any]]] = field(repr=False)
    _set_value: Callable[[Any], None] = field(repr=False)

    def set_value(self, value: Any) -> None:
        self._set_value(copy.deepcopy(value))
        self.value = copy.deepcopy(value)

    def load_reference(self, reference: ReferenceConfig, *, extra_params: Mapping[str, Any] | None = None) -> list[dict[str, Any]]:
        """Use configured reference handlers/cache for the current environment."""
        return copy.deepcopy(self._load_reference(reference, self.environment, dict(extra_params or {})))

    def get_selected_items(self, key: str) -> list[dict[str, Any]]:
        """Full resolved items; dialog fields take precedence over form fields."""
        return copy.deepcopy(self._selected_items(key))


@dataclass(frozen=True)
class FieldDialogAction:
    action_id: str
    label: str
    handler: Callable[[FieldActionContext], Any]
    style: str = "Primary"
    require_valid_dialog: bool = True
    confirmation_text: str = ""
    close_on_success: bool = True


def apply_field_return(context: FieldActionContext, result: Any) -> Any:
    """Stage a plain return value; preserve typed and legacy action responses.

    None leaves the field unchanged. Explicit set_value calls are also staged.
    Mappings containing response metadata retain the legacy response meaning;
    use set_value for a BLOCK value whose keys overlap those names.
    """
    from forms.base_form import ServerActionResult, ServerDialogActionResult

    if result is None or isinstance(result, (ServerActionResult, ServerDialogActionResult)):
        return result
    metadata = {"message", "status", "title", "values", "form_values", "dialog_values", "data", "close_dialog"}
    if isinstance(result, Mapping) and metadata.intersection(result):
        return result
    context.set_value(result)
    return None


@dataclass(frozen=True)
class FieldActionDialog:
    """Declarative, non-blocking dialog. Button handlers receive the selection.

    ``initial_values(context)`` runs once on opening; ``validate(context)``
    should be read-only. Reference fields retain normal search, refresh and
    explicit ReferenceDependency rules, including scope="form".
    """

    title: str
    fields: Sequence[FieldDefinition]
    actions: Sequence[FieldDialogAction]
    description: str = ""
    initial_values: Mapping[str, Any] | Callable[[FieldActionContext], Mapping[str, Any]] = field(default_factory=dict)
    validate: Callable[[FieldActionContext], Any] | None = None


@dataclass(frozen=True)
class FieldAction:
    """Declare exactly one direct ``handler(context)`` or ``dialog``.

    Direct handlers may return ServerActionResult; dialog handlers may return
    ServerDialogActionResult. Use context.set_value for the owning field.
    Declaration/factory code must not perform I/O; perform it in callbacks.
    """

    action_id: str
    label: str
    handler: Callable[[FieldActionContext], Any] | None = None
    dialog: FieldActionDialog | None = None
    style: str = "Secondary"
    require_valid_form: bool = False
    confirmation_text: str = ""
