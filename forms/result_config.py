"""
ResultScreenConfig — конфигурация экрана результата после отправки формы.
Возвращается методом BaseForm.get_result_config().
"""
from dataclasses import dataclass, field


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
