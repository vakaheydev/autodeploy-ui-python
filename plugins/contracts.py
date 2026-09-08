"""UI-independent contracts for server-rendered custom plugin pages.

Plugins are Python extensions.  React only renders the JSON projection produced
by :mod:`webapp.plugin_runtime`; business rules and side effects never move to
the browser.
"""
from __future__ import annotations

import base64
from dataclasses import dataclass, field
from typing import Any, Callable, Mapping, Optional, Sequence, Union

from core.env_manager import EnvManager
from core.http_client import HttpClient
from core.reference_resolver import ReferenceResolver
from forms.base_form import FormValidationIssue
from forms.fields import FieldDefinition


@dataclass(frozen=True)
class PluginContext:
    """Fresh server-side dependencies supplied for one plugin request.

    ``services`` is the object returned by ``AUTODEPLOY_SERVICE_PROVIDER`` and
    normally exposes ``itsm``, ``tfs`` and ``gravitee``.  It is deliberately
    typed as ``Any`` so a corporate provider may expose additional services
    without changing the public core.
    """

    environment: str
    env_manager: EnvManager
    http_client: HttpClient
    reference_resolver: ReferenceResolver
    services: Any


@dataclass(frozen=True)
class TextWidget:
    widget_id: str
    text: str
    title: str = ""
    tone: str = "default"  # default | info | success | warning | danger
    kind: str = field(default="text", init=False)


@dataclass(frozen=True)
class MetricWidget:
    widget_id: str
    label: str
    value: str | int | float
    detail: str = ""
    tone: str = "default"
    kind: str = field(default="metric", init=False)


@dataclass(frozen=True)
class ImageWidget:
    widget_id: str
    src: str
    alt: str
    title: str = ""
    caption: str = ""
    kind: str = field(default="image", init=False)

    @classmethod
    def from_bytes(
        cls,
        widget_id: str,
        content: bytes,
        *,
        mime_type: str,
        alt: str,
        title: str = "",
        caption: str = "",
    ) -> "ImageWidget":
        """Build an in-memory image accepted by the same-origin CSP.

        Keep generated images reasonably small: they are serialized into the
        API response as a ``data:`` URL.
        """

        encoded = base64.b64encode(bytes(content)).decode("ascii")
        return cls(
            widget_id=widget_id,
            src=f"data:{mime_type};base64,{encoded}",
            alt=alt,
            title=title,
            caption=caption,
        )


@dataclass(frozen=True)
class ChartSeries:
    name: str
    values: Sequence[float | int]
    color: str = ""


@dataclass(frozen=True)
class ChartWidget:
    widget_id: str
    labels: Sequence[str]
    series: Sequence[ChartSeries]
    title: str = ""
    chart_type: str = "line"  # line | area | bar | pie | doughnut
    y_label: str = ""
    kind: str = field(default="chart", init=False)


@dataclass(frozen=True)
class TableWidget:
    widget_id: str
    columns: Sequence[str]
    rows: Sequence[Sequence[Any]]
    title: str = ""
    kind: str = field(default="table", init=False)


PluginWidget = Union[
    TextWidget,
    MetricWidget,
    ImageWidget,
    ChartWidget,
    TableWidget,
    Mapping[str, Any],
]


@dataclass(frozen=True)
class PluginView:
    """Dynamic content returned by ``PluginDefinition.render``."""

    widgets: Sequence[PluginWidget] = ()


PluginValidationIssue = str | FormValidationIssue | Mapping[str, Any]
PluginRenderer = Callable[[PluginContext, Mapping[str, Any]], PluginView | Sequence[PluginWidget] | None]
PluginValidator = Callable[[PluginContext, Mapping[str, Any]], Sequence[PluginValidationIssue] | PluginValidationIssue | None]
PluginOperationHandler = Callable[[PluginContext, Mapping[str, Any]], Any]


@dataclass(frozen=True)
class PluginOperation:
    """A server-side button and, when allowed, a dedicated MCP tool.

    ``handler`` receives the authoritative context and normalized current page
    values.  It may perform any corporate operation.  AI access is not declared
    here: operators configure ``deny``, ``allow`` or ``manual`` independently
    in the web settings.
    """

    operation_id: str
    label: str
    handler: PluginOperationHandler
    description: str = ""
    ai_description: str = ""
    style: str = "secondary"  # primary | secondary | success | danger
    confirmation_text: str = ""
    require_valid_fields: bool = True
    read_only: bool = False
    idempotent: bool = False
    open_world: bool = True


@dataclass(frozen=True)
class PluginActionResult:
    """Optional result envelope returned by an operation handler.

    ``values`` is a partial patch.  ``widgets`` can supply an immediate result;
    when omitted, the plugin renderer is called again after applying the patch.
    ``data`` remains available to API clients but is rendered only as JSON when
    no richer widget was provided.
    """

    message: str = "Действие выполнено"
    values: Mapping[str, Any] = field(default_factory=dict)
    widgets: Optional[Sequence[PluginWidget]] = None
    data: Any = None


@dataclass(frozen=True)
class PluginDefinition:
    """Complete declaration of one corporate custom page."""

    plugin_id: str
    title: str
    description: str = ""
    category: str = "Корпоративные"
    icon: str = "puzzle"
    keywords: Sequence[str] = ()
    fields: Sequence[FieldDefinition] = ()
    operations: Sequence[PluginOperation] = ()
    render: Optional[PluginRenderer] = None
    validate: Optional[PluginValidator] = None
