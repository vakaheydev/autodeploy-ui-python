"""Public contracts for corporate AutoDeploy page plugins.

The package intentionally contains no corporate implementation.  Private
packages register :class:`PluginDefinition` objects through the public runtime
extension point documented in ``docs/corp/PLUGINS.md``.
"""

from plugins.contracts import (
    ChartSeries,
    ChartWidget,
    ImageWidget,
    MetricWidget,
    PluginActionResult,
    PluginContext,
    PluginDefinition,
    PluginOperation,
    PluginView,
    TableWidget,
    TextWidget,
)
from plugins.registry import PluginRegistry

__all__ = [
    "ChartSeries",
    "ChartWidget",
    "ImageWidget",
    "MetricWidget",
    "PluginActionResult",
    "PluginContext",
    "PluginDefinition",
    "PluginOperation",
    "PluginRegistry",
    "PluginView",
    "TableWidget",
    "TextWidget",
]
