"""
Форма: АПИ / Создание АПИ.

TODO: заменить заглушки реальными URL и маппингом payload.
"""
from typing import Any, Dict, List

from forms.base_form import BaseForm
from forms.fields import FieldDefinition, FieldType, ReferenceConfig

# TODO: перенести URL в конфигурационный файл или переменные окружения
_SUBMIT_URLS: Dict[str, str] = {
    "test_int":    "https://api.test-int.example.com/management/v2/apis",
    "test_ext":    "https://api.test-ext.example.com/management/v2/apis",
    "regress_int": "https://api.regress-int.example.com/management/v2/apis",
    "regress_ext": "https://api.regress-ext.example.com/management/v2/apis",
    "prod_int":    "https://api.prod-int.example.com/management/v2/apis",
    "prod_ext":    "https://api.prod-ext.example.com/management/v2/apis",
}


class CreateApiForm(BaseForm):
    """Форма создания нового АПИ в Gravitee."""

    @property
    def form_id(self) -> str:
        return "api.create"

    @property
    def title(self) -> str:
        return "Создание АПИ"

    @property
    def category(self) -> str:
        return "api"

    @property
    def fields(self) -> List[FieldDefinition]:
        return [
            FieldDefinition(
                key="name",
                label="Название АПИ",
                field_type=FieldType.TEXT,
                placeholder="Введите название АПИ",
            ),
            FieldDefinition(
                key="description",
                label="Описание АПИ",
                field_type=FieldType.TEXTAREA,
                placeholder="Краткое описание назначения АПИ",
                required=False,
            ),
            FieldDefinition(
                key="owner",
                label="Владелец АПИ",
                field_type=FieldType.TEXT,
                placeholder="Имя команды или ответственного",
            ),
            FieldDefinition(
                key="category",
                label="Категория АПИ",
                field_type=FieldType.SELECT,
                reference=ReferenceConfig(
                    source="local",
                    resource="api_categories.json",
                    value_key="id",
                    label_key="name",
                ),
            ),
            FieldDefinition(
                key="context_path",
                label="Контекстный путь",
                field_type=FieldType.TEXT,
                placeholder="/api/v1/my-service",
            ),
            FieldDefinition(
                key="endpoint_type",
                label="Тип эндпоинта",
                field_type=FieldType.SELECT,
                reference=ReferenceConfig(
                    source="local",
                    resource="endpoint_types.json",
                    value_key="id",
                    label_key="name",
                ),
            ),
        ]

    def build_payload(self, form_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        TODO: привести структуру payload к формату реального API Gravitee.
        Сейчас — прямое отображение полей формы.
        """
        return {
            "name":         form_data.get("name", ""),
            "description":  form_data.get("description", ""),
            "owner":        form_data.get("owner", ""),
            "categoryId":   form_data.get("category", ""),
            "contextPath":  form_data.get("context_path", ""),
            "endpointType": form_data.get("endpoint_type", ""),
        }

    def get_submit_endpoint(self, environment: str) -> str:
        return _SUBMIT_URLS.get(environment, "")
