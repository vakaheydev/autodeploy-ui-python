"""Выбор конкретного OpenCode thinking variant для AI-операций."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable


AUTO_THINKING_MODE = "auto"
FIXED_THINKING_VARIANTS = ("none", "low", "medium", "xhigh")

@dataclass(frozen=True)
class ThinkingDecision:
    """Фактически отправляемый variant и короткое объяснение для UI/логов."""

    variant: str
    reason: str


def ordered_thinking_variants(variants: Iterable[str]) -> tuple[str, ...]:
    """Возвращает variants из конфига в понятном порядке без выдуманных значений."""
    unique: dict[str, str] = {}
    for value in variants:
        clean = str(value).strip()
        if clean:
            unique.setdefault(clean.casefold(), clean)
    ordered = [
        unique.pop(canonical)
        for canonical in FIXED_THINKING_VARIANTS
        if canonical in unique
    ]
    ordered.extend(unique.values())
    return tuple(ordered)


def _resolve_variant(desired: str, available: Iterable[str]) -> str:
    configured = {
        str(value).strip().casefold(): str(value).strip()
        for value in available
        if str(value).strip()
    }
    fallback_order = {
        "none": ("none", "low", "medium"),
        "low": ("low", "none", "medium"),
        "medium": ("medium", "low", "none"),
        "xhigh": ("xhigh", "medium", "low", "none"),
    }.get(desired, (desired, "none", "low", "medium"))
    for candidate in fallback_order:
        if candidate in configured:
            return configured[candidate]
    raise ValueError(
        "У выбранной модели в opencode.json нет none, low или medium для режима "
        "Авто. Выберите доступный thinking variant вручную."
    )


def decide_copilot_thinking(
    *,
    has_ticket: bool = False,
    diagnostic_data: Any = None,
    workflow_hint: str = "",
    available_variants: Iterable[str],
) -> ThinkingDecision:
    """Выбирает Auto только по состоянию workflow, не анализируя текст запроса."""
    if diagnostic_data is not None:
        desired = "medium"
        reason = "к запросу приложены данные диагностики"
    elif workflow_hint == "plan":
        desired = "medium"
        reason = "пользователь выбрал команду построения плана"
    elif has_ticket:
        desired = "low"
        reason = "к запросу приложена заявка"
    else:
        desired = "none"
        reason = "свободный текст обрабатывается без Python-классификации"
    actual = _resolve_variant(desired, available_variants)
    if actual.casefold() != desired:
        reason += f"; {desired} недоступен, выбран {actual}"
    return ThinkingDecision(actual, reason)


def decide_extractor_thinking(
    mode: str,
    *,
    missing_information: Iterable[str] = (),
    research_goal: str = "",
    available_variants: Iterable[str],
) -> ThinkingDecision:
    """Ускоряет extractor, когда Copilot уже подготовил все значения формы."""
    missing = tuple(value for value in missing_information if str(value).strip())
    if mode == "fill_only":
        desired = "none"
        reason = "Copilot уже передал готовые значения формы"
    elif len(missing) >= 3:
        desired = "medium"
        reason = "extractor должен исследовать несколько неизвестных"
    else:
        desired = "low"
        reason = "extractor должен найти недостающий факт"
    actual = _resolve_variant(desired, available_variants)
    if actual.casefold() != desired:
        reason += f"; {desired} недоступен, выбран {actual}"
    return ThinkingDecision(actual, reason)
