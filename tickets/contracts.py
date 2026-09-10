"""Contracts implemented by a private package to expose corporate tickets.

The public core owns transport and rendering only.  Ticket retrieval, filtering,
sorting, card contents and button handlers remain in the private Python package.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Mapping, Protocol, Sequence

from core.env_manager import EnvManager
from core.http_client import HttpClient


@dataclass(frozen=True)
class TicketContext:
    """Fresh request-scoped dependencies passed to every corporate method."""

    environment: str
    env_manager: EnvManager
    http_client: HttpClient
    services: Any


@dataclass(frozen=True)
class TicketFilterOption:
    value: str
    label: str


@dataclass(frozen=True)
class TicketFilterDefinition:
    """One server-declared list filter rendered by the generic frontend.

    Supported kinds are ``text``, ``select``, ``multiselect``, ``date`` and
    ``boolean``.  Select kinds should provide a bounded list of options.
    """

    key: str
    label: str
    kind: str = "select"
    options: Sequence[TicketFilterOption] = ()
    placeholder: str = ""
    default: Any = None


@dataclass(frozen=True)
class TicketSortDefinition:
    key: str
    label: str


@dataclass(frozen=True)
class TicketListConfiguration:
    """Corporate declaration for the list toolbar and empty state."""

    description: str = ""
    filters: Sequence[TicketFilterDefinition] = ()
    sorts: Sequence[TicketSortDefinition] = ()
    default_sort: str = ""
    default_direction: str = "desc"
    page_size: int = 25
    empty_title: str = "Заявок пока нет"
    empty_text: str = "Измените фильтры или повторите поиск позже."


@dataclass(frozen=True)
class TicketListRequest:
    """Normalized query supplied to ``load_current_tickets``/``find_tickets``."""

    environment: str
    query: str = ""
    filters: Mapping[str, Any] = field(default_factory=dict)
    sort_key: str = ""
    sort_direction: str = "desc"
    offset: int = 0
    limit: int = 25


@dataclass(frozen=True)
class TicketAttribute:
    """A safe value shown in a list item or a card section.

    ``kind`` may be ``text``, ``multiline``, ``code``, ``datetime``, ``badge``
    or ``json``.  ``url`` is optional and is restricted by the public runtime to
    same-origin paths or HTTP(S) links.
    """

    key: str
    label: str
    value: Any
    kind: str = "text"
    url: str = ""
    copyable: bool = False
    tone: str = "default"


@dataclass(frozen=True)
class TicketListItem:
    ticket_id: str
    title: str
    subtitle: str = ""
    status: str = ""
    status_tone: str = "default"
    updated_at: str = ""
    attributes: Sequence[TicketAttribute] = ()


@dataclass(frozen=True)
class TicketPage:
    items: Sequence[TicketListItem]
    total: int


@dataclass(frozen=True)
class TicketSection:
    section_id: str
    title: str
    attributes: Sequence[TicketAttribute]


TicketActionHandler = Callable[[TicketContext, str], Any]


@dataclass(frozen=True)
class TicketAction:
    """A corporate Python method projected as one button on the ticket card.

    ``style`` supports ``primary``, ``secondary``, ``success``, ``danger`` and
    ``warning``.  ``color`` can override the background using ``#RGB`` or
    ``#RRGGBB``.  Destructive operations should always set
    ``confirmation_text``.
    """

    action_id: str
    label: str
    handler: TicketActionHandler
    description: str = ""
    style: str = "secondary"
    color: str = ""
    confirmation_text: str = ""
    disabled_reason: str = ""


@dataclass(frozen=True)
class TicketActionResult:
    message: str = "Действие выполнено"
    data: Any = None
    reload_card: bool = True


@dataclass(frozen=True)
class TicketCard:
    ticket_id: str
    title: str
    subtitle: str = ""
    description: str = ""
    status: str = ""
    status_tone: str = "default"
    updated_at: str = ""
    sections: Sequence[TicketSection] = ()
    actions: Sequence[TicketAction] = ()


class TicketProvider(Protocol):
    """Required interface returned by ``AUTODEPLOY_TICKET_PROVIDER``."""

    def get_list_configuration(
        self, context: TicketContext
    ) -> TicketListConfiguration:
        ...

    def load_current_tickets(
        self, context: TicketContext, request: TicketListRequest
    ) -> TicketPage:
        ...

    def find_tickets(
        self, context: TicketContext, request: TicketListRequest
    ) -> TicketPage:
        ...

    def load_ticket_card_by_id(
        self, context: TicketContext, ticket_id: str
    ) -> TicketCard:
        ...


class TicketUserError(ValueError):
    """A safe corporate error that may be shown verbatim to the operator."""


class TicketNotFound(LookupError):
    """Raised by a corporate provider when a ticket no longer exists."""
