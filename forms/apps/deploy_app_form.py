"""
Форма: Приложения / Деплой приложения.

TODO: реализовать поля, payload и URL.
"""
from typing import Any, Dict, List

from forms.base_form import BaseForm
from forms.fields import FieldDefinition, FieldType, ReferenceConfig

# TODO: заменить заглушки реальными URL
_SUBMIT_URLS: Dict[str, str] = {
    "test_int":    "https://deploy.test-int.example.com/api/deploy",
    "test_ext":    "https://deploy.test-ext.example.com/api/deploy",
    "regress_int": "https://deploy.regress-int.example.com/api/deploy",
    "regress_ext": "https://deploy.regress-ext.example.com/api/deploy",
    "prod_int":    "https://deploy.prod-int.example.com/api/deploy",
    "prod_ext":    "https://deploy.prod-ext.example.com/api/deploy",
}


class DeployAppForm(BaseForm):
    """Форма запуска деплоя приложения."""

    @property
    def form_id(self) -> str:
        return "apps.deploy"

    @property
    def title(self) -> str:
        return "Деплой приложения"

    @property
    def category(self) -> str:
        return "apps"

    @property
    def fields(self) -> List[FieldDefinition]:
        # TODO: добавить реальные поля формы деплоя
        return [
            FieldDefinition(
                key="app_name",
                label="Название приложения",
                field_type=FieldType.TEXT,
                placeholder="my-service",
            ),
            FieldDefinition(
                key="version",
                label="Версия (тег/ветка)",
                field_type=FieldType.TEXT,
                placeholder="v1.2.3 или feature/my-branch",
            ),
            FieldDefinition(
                key="namespace",
                label="Namespace",
                field_type=FieldType.TEXT,
                placeholder="default",
                required=False,
            ),
            FieldDefinition(
                key="replicas",
                label="Количество реплик",
                field_type=FieldType.NUMBER,
                default=1,
                required=False,
            ),
        ]

    def build_payload(self, form_data: Dict[str, Any]) -> Dict[str, Any]:
        # TODO: реализовать реальный payload для деплоя
        return {
            "appName":   form_data.get("app_name", ""),
            "version":   form_data.get("version", ""),
            "namespace": form_data.get("namespace", "default"),
            "replicas":  form_data.get("replicas", 1),
        }

    def get_submit_endpoint(self, environment: str) -> str:
        return _SUBMIT_URLS.get(environment, "")
