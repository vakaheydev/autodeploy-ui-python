"""
Loader — единое место регистрации всех форм.

Чтобы добавить новую форму:
  1. Создать класс в соответствующей папке (forms/api/, forms/apps/, forms/other/)
  2. Импортировать и зарегистрировать здесь — больше ничего менять не нужно.
"""
from forms.registry import FormRegistry
from forms.api.create_api_form import CreateApiForm
from forms.apps.deploy_app_form import DeployAppForm
from forms.other.enable_ingress_form import EnableIngressForm
from forms.other.disable_ingress_form import DisableIngressForm


def register_all_forms() -> None:
    """Регистрирует все формы приложения в FormRegistry."""
    registry = FormRegistry()

    # --- Категория: АПИ ---
    registry.register(CreateApiForm())
    # registry.register(UpdateApiForm())      # TODO
    # registry.register(DeleteApiForm())      # TODO

    # --- Категория: Приложения ---
    registry.register(DeployAppForm())
    # registry.register(RollbackAppForm())    # TODO

    # --- Категория: Операции ---
    registry.register(EnableIngressForm())
    registry.register(DisableIngressForm())
    # registry.register(AccessRequestForm())  # TODO
