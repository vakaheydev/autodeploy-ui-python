"""
ResultScreenConfig — конфигурация экрана результата после отправки формы.
Возвращается методом BaseForm.get_result_config().
"""
from dataclasses import dataclass
from enum import Enum


class ResultStatus(Enum):
    """
    Визуальный статус на экране результата.

    PENDING  — серые часы ◷      (принято, ожидает обработки)
    SUCCESS  — зелёная галочка ✓ (операция завершена успешно)
    WAITING  — жёлтые часы ⏳   (в процессе / активный опрос)
    ERROR    — красный крест ✗   (ошибка)
    """
    PENDING = "pending"
    SUCCESS = "success"
    WAITING = "waiting"
    ERROR   = "error"


@dataclass
class ResultScreenConfig:
    """
    Конфигурация экрана результата.

    poll_interval_ms  — интервал автообновления в миллисекундах.
                        None (по умолчанию) — автообновление отключено.
    title             — заголовок экрана результата.
                        По умолчанию используется заголовок формы.
    """
    poll_interval_ms: int | None = None
    title: str | None = None          # None → будет использован form.title
