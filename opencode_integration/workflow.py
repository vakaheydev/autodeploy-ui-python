"""Состояние подтверждённого многоформового плана и AI handoff."""
from __future__ import annotations

import copy
import threading
import uuid
from dataclasses import dataclass, field
from typing import Any, Optional

from opencode_integration.context_builder import BuiltContext
from opencode_integration.thinking import AUTO_THINKING_MODE, decide_extractor_thinking


PLAN_STATUSES = ("pending", "in_progress", "prepared", "completed", "failed")
EXTRACTOR_MODES = ("fill_only", "research")


@dataclass(frozen=True)
class AIFieldProposal:
    field_key: str
    value: Any
    source: str
    confidence: str = "unknown"


@dataclass(frozen=True)
class ExtractionDirective:
    """Проверенная команда Copilot для следующего form-extractor."""

    form_id: str
    mode: str
    field_proposals: tuple[AIFieldProposal, ...] = ()
    missing_information: tuple[str, ...] = ()
    research_goal: str = ""


@dataclass(frozen=True)
class PlannedFormStep:
    step_id: str
    position: int
    form_id: str
    title: str
    reason: str
    depends_on: tuple[str, ...] = ()
    confidence: str = "unknown"
    extraction: Optional[ExtractionDirective] = None


@dataclass
class RuntimePlanStep:
    spec: PlannedFormStep
    status: str = "pending"
    error: str = ""
    form_data: dict = field(default_factory=dict)


@dataclass(frozen=True)
class AIFormHandoff:
    context: BuiltContext
    plan_id: str = ""
    step_id: str = ""
    guidance: str = ""
    provider_id: str = ""
    model_id: str = ""
    variant: str = ""
    thinking_auto: bool = False
    extraction: Optional[ExtractionDirective] = None


@dataclass
class ExecutionPlanState:
    """Потокобезопасный in-memory план; внешних действий сам не выполняет."""

    ticket_id: str
    context: BuiltContext
    steps: list[RuntimePlanStep]
    title: str = "План исполнения заявки"
    shared_guidance: str = ""
    provider_id: str = ""
    model_id: str = ""
    variant: str = ""
    thinking_mode: str = ""
    available_variants: tuple[str, ...] = ()
    plan_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    _lock: threading.RLock = field(
        default_factory=threading.RLock,
        init=False,
        repr=False,
    )

    @classmethod
    def from_specs(
        cls,
        *,
        context: BuiltContext,
        specs: tuple[PlannedFormStep, ...],
        title: str = "План исполнения заявки",
        shared_guidance: str = "",
        provider_id: str = "",
        model_id: str = "",
        variant: str = "",
        thinking_mode: str = "",
        available_variants: tuple[str, ...] = (),
    ) -> "ExecutionPlanState":
        return cls(
            ticket_id=context.ticket_id,
            context=context,
            steps=[RuntimePlanStep(spec=item) for item in specs],
            title=title,
            shared_guidance=str(shared_guidance)[:20_000],
            provider_id=provider_id,
            model_id=model_id,
            variant=variant,
            thinking_mode=thinking_mode,
            available_variants=tuple(available_variants),
        )

    def snapshot(self) -> tuple[RuntimePlanStep, ...]:
        with self._lock:
            return tuple(
                RuntimePlanStep(
                    item.spec,
                    item.status,
                    item.error,
                    copy.deepcopy(item.form_data),
                )
                for item in self.steps
            )

    def get(self, step_id: str) -> RuntimePlanStep:
        with self._lock:
            for item in self.steps:
                if item.spec.step_id == step_id:
                    return item
        raise KeyError(f"Шаг плана {step_id!r} не найден")

    def can_open(self, step_id: str) -> bool:
        with self._lock:
            item = self.get(step_id)
            completed = {
                candidate.spec.step_id
                for candidate in self.steps
                if candidate.status == "completed"
            }
            return (
                item.status != "completed"
                and all(dependency in completed for dependency in item.spec.depends_on)
            )

    def mark(
        self,
        step_id: str,
        status: str,
        error: str = "",
        form_data: Optional[dict] = None,
    ) -> None:
        if status not in PLAN_STATUSES:
            raise ValueError(f"Неизвестный статус шага плана: {status}")
        with self._lock:
            item = self.get(step_id)
            item.status = status
            item.error = str(error)[:1000] if status == "failed" else ""
            if form_data is not None:
                item.form_data = copy.deepcopy(form_data)
            if status == "completed":
                item.form_data = {}

    @property
    def complete(self) -> bool:
        with self._lock:
            return bool(self.steps) and all(
                item.status == "completed" for item in self.steps
            )

    def handoff(self, step_id: str) -> AIFormHandoff:
        with self._lock:
            item = self.get(step_id)
            if not self.can_open(step_id):
                raise ValueError("Сначала завершите зависимые шаги плана")
            item.status = "in_progress"
            guidance = (
                f"Execution plan step {item.spec.position}: {item.spec.title}. "
                f"Purpose: {item.spec.reason}. Fill only this form step; do not "
                "perform actions belonging to other steps."
                + (f"\nShared validated copilot context:\n{self.shared_guidance}"
                   if self.shared_guidance else "")
            )
            variant = self.variant
            thinking_auto = self.thinking_mode == AUTO_THINKING_MODE
            if thinking_auto:
                extraction = item.spec.extraction
                decision = decide_extractor_thinking(
                    extraction.mode if extraction is not None else "research",
                    missing_information=(
                        extraction.missing_information if extraction is not None else ()
                    ),
                    research_goal=(
                        extraction.research_goal if extraction is not None else ""
                    ),
                    available_variants=self.available_variants,
                )
                variant = decision.variant
            return AIFormHandoff(
                context=self.context,
                plan_id=self.plan_id,
                step_id=item.spec.step_id,
                guidance=guidance,
                provider_id=self.provider_id,
                model_id=self.model_id,
                variant=variant,
                thinking_auto=thinking_auto,
                extraction=item.spec.extraction,
            )
