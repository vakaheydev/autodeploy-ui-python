"""
Форма: Операции / Выключение ингрессов.
"""
from typing import Any, Dict, List

from forms.base_form import BaseForm
from forms.fields import FieldCondition, FieldDefinition, FieldType, ReferenceConfig

_SUBMIT_URLS: Dict[str, str] = {
    "test_int":    "https://ops.test-int.example.com/api/ingress/disable",
    "test_ext":    "https://ops.test-ext.example.com/api/ingress/disable",
    "regress_int": "https://ops.regress-int.example.com/api/ingress/disable",
    "regress_ext": "https://ops.regress-ext.example.com/api/ingress/disable",
    "prod_int":    "https://ops.prod-int.example.com/api/ingress/disable",
    "prod_ext":    "https://ops.prod-ext.example.com/api/ingress/disable",
}


class DisableIngressForm(BaseForm):
    """Форма выключения ингрессов для выбранных приложений."""

    @property
    def form_id(self) -> str:
        return "other.ingress.disable"

    @property
    def title(self) -> str:
        return "Выключение ингрессов"

    @property
    def category(self) -> str:
        return "other"

    @property
    def fields(self) -> List[FieldDefinition]:
        return [
            FieldDefinition(
                key="apps",
                label="Приложения",
                field_type=FieldType.MULTISELECT,
                # TODO: заменить source на "http" когда будет готов эндпоинт
                reference=ReferenceConfig(
                    source="local",
                    resource="applications.json",
                    value_key="id",
                    label_key="name",
                    search_keys=("name", "azp", "id"),
                ),
            ),
            FieldDefinition(
                key="ingress_type",
                label="Тип ингресса",
                field_type=FieldType.SELECT,
                reference=ReferenceConfig(
                    source="local",
                    resource="ingress_types.json",
                    value_key="id",
                    label_key="name",
                ),
            ),
            FieldDefinition(
                key="channel_type",
                label="Тип канала",
                field_type=FieldType.SELECT,
                required=False,
                reference=ReferenceConfig(
                    source="local",
                    resource="channel_types.json",
                    value_key="id",
                    label_key="name",
                ),
                condition=FieldCondition(
                    field_key="ingress_type",
                    value="platformeco",
                ),
            ),
        ]

    def validate(self, form_data: Dict[str, Any]) -> List[str]:
        errors = super().validate(form_data)
        if form_data.get("ingress_type") == "platformeco":
            if not form_data.get("channel_type"):
                errors.append('"Тип канала" обязателен для типа ингресса platformeco')
        if not form_data.get("apps"):
            errors.append('Необходимо выбрать хотя бы одно приложение')
        return errors

    def build_payload(self, form_data: Dict[str, Any]) -> Dict[str, Any]:
        # TODO: привести к формату реального API
        payload: Dict[str, Any] = {
            "apps":        form_data.get("apps", []),
            "ingressType": form_data.get("ingress_type", ""),
        }
        if form_data.get("ingress_type") == "platformeco":
            payload["channelType"] = form_data.get("channel_type", "")
        return payload

    def get_submit_endpoint(self, environment: str) -> str:
        return _SUBMIT_URLS.get(environment, "")
