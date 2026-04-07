"""
Форма: Другое / Создание заявки.

TODO: реализовать поля, payload и URL.
"""
from typing import Any, Dict, List

from forms.base_form import BaseForm
from forms.fields import FieldDefinition, FieldType

# TODO: заменить заглушки реальными URL
_SUBMIT_URLS: Dict[str, str] = {
    "test_int":    "https://jira.test-int.example.com/api/requests",
    "test_ext":    "https://jira.test-ext.example.com/api/requests",
    "regress_int": "https://jira.regress-int.example.com/api/requests",
    "regress_ext": "https://jira.regress-ext.example.com/api/requests",
    "prod_int":    "https://jira.prod-int.example.com/api/requests",
    "prod_ext":    "https://jira.prod-ext.example.com/api/requests",
}


class CreateRequestForm(BaseForm):
    """Форма создания произвольной заявки."""

    @property
    def form_id(self) -> str:
        return "other.request"

    @property
    def title(self) -> str:
        return "Создание заявки"

    @property
    def category(self) -> str:
        return "other"

    @property
    def fields(self) -> List[FieldDefinition]:
        # TODO: добавить реальные поля
        return [
            FieldDefinition(
                key="subject",
                label="Тема заявки",
                field_type=FieldType.TEXT,
                placeholder="Кратко опишите суть",
            ),
            FieldDefinition(
                key="description",
                label="Описание",
                field_type=FieldType.TEXTAREA,
                placeholder="Подробное описание",
            ),
            FieldDefinition(
                key="assignee",
                label="Исполнитель",
                field_type=FieldType.TEXT,
                placeholder="login или email",
                required=False,
            ),
        ]

    def build_payload(self, form_data: Dict[str, Any]) -> Dict[str, Any]:
        # TODO: реализовать реальный payload
        return {
            "subject":     form_data.get("subject", ""),
            "description": form_data.get("description", ""),
            "assignee":    form_data.get("assignee", ""),
        }

    def get_submit_endpoint(self, environment: str) -> str:
        return _SUBMIT_URLS.get(environment, "")
