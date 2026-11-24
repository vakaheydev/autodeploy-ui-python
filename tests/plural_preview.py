"""Offline FormScreen fixture; run with python -m tests.plural_preview."""
import tkinter as tk
from types import SimpleNamespace
from unittest.mock import Mock

from forms.base_form import BaseForm
from forms.fields import FieldDefinition, FieldType
from forms.registry import FormRegistry
from ui.screens.form_screen import FormScreen
import ui.theme as theme


class PreviewForm(BaseForm):
    form_id = "test.plural_preview"
    title = "Динамические блоки"
    category = "other"
    fields = [
        FieldDefinition("service", "Сервис", FieldType.BLOCK, plural=True, plural_max=4,
            block_fields=[
                FieldDefinition("name", "Название", FieldType.TEXT),
                FieldDefinition("path", "Путь", FieldType.TEXT),
            ]),
    ]

    def build_payload(self, form_data):
        return {"services": self.collect_plural(form_data, "service")}

    def get_submit_endpoint(self, environment):
        return ""


def make_screen(root, form=None):
    form = form or PreviewForm()
    FormRegistry().register(form)
    app = SimpleNamespace(
        current_environment=tk.StringVar(root, value="test"),
        http_client=Mock(), reference_resolver=Mock(), reference_cache=Mock(),
        itsm_service=None, tfs_service=None, gravitee_service=None,
        go_back=lambda: None, go_home=lambda: None,
        release_execution_plan_step=lambda *args, **kwargs: None,
    )
    return FormScreen(root, app, form_id=form.form_id)


if __name__ == "__main__":
    root = tk.Tk()
    root.title("AutoDeploy — проверка динамических блоков")
    root.geometry("960x880")
    theme.apply(root)
    screen = make_screen(root)
    screen.pack(fill=tk.BOTH, expand=True, padx=24, pady=20)
    screen.apply_form_data({
        "service": {"name": "Сервис каталога", "path": "/catalog"},
        "service_2": {"name": "Сервис заказов", "path": "/orders"},
    })
    # This preview cannot submit or make network requests.
    screen._submit_button.configure(state=tk.DISABLED)
    root.mainloop()
