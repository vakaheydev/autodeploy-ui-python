"""The desktop form remains usable without an OpenCode client or AI callbacks."""
import subprocess
import sys
import tkinter as tk
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from forms.fields import FieldDefinition, FieldType
from tests.plural_preview import PreviewForm, make_screen
from ui.screens.form_screen import FormScreen


class ManualForm(PreviewForm):
    form_id = "test.manual_without_ai"
    fields = [FieldDefinition("name", "Название", FieldType.TEXT)]
    itsm_support = True

    def confirm_submit(self):
        return True

    def build_payload(self, data):
        return dict(data)

    def fetch_from_itsm(self, environment, ticket_id):
        return {"name": "from ticket"}


class FormWithoutOpenCodeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root = tk.Tk()
        cls.root.withdraw()

    @classmethod
    def tearDownClass(cls):
        cls.root.destroy()

    def setUp(self):
        self.screen = make_screen(self.root, ManualForm())
        self.screen.app.submit_service = Mock()
        self.screen.app.run_storage = Mock()
        self.screen.app.navigate_to = Mock()
        del self.screen.app.release_execution_plan_step

    def tearDown(self):
        for child in self.root.winfo_children():
            child.destroy()

    def test_import_does_not_require_opencode(self):
        script = """
import importlib.abc
import sys
class BlockAI(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.startswith(('opencode_integration', 'ui.ai_assistant', 'ui.inline_ai_review')):
            raise ImportError('AI dependency was requested: ' + fullname)
sys.meta_path.insert(0, BlockAI())
from ui.screens.form_screen import FormScreen
"""
        result = subprocess.run(
            [sys.executable, "-c", script], cwd=Path(__file__).resolve().parents[1],
            capture_output=True, text=True, timeout=30,
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_legacy_navigation_does_not_start_ai_and_keeps_itsm_button(self):
        app = self.screen.app
        app.opencode_manager = Mock()
        app.consume_ai_handoff = Mock(side_effect=AssertionError("AI must not start"))
        self.screen.destroy()
        self.screen = FormScreen(
            self.root, app, form_id=ManualForm.form_id,
            ai_autostart=True, plan_id="old-plan", plan_step_id="old-step",
        )
        self.root.update()
        app.consume_ai_handoff.assert_not_called()
        self.assertEqual(app.opencode_manager.mock_calls, [])
        labels = [child.cget("text") for child in self.screen._normal_footer.winfo_children()]
        self.assertIn("⬇ Подтянуть из заявки", labels)
        self.assertFalse(any("AI" in label or "✨" in label for label in labels))
        app.current_environment.set("another-environment")
        self.screen.destroy()

    def test_direct_itsm_fetch_still_populates_fields(self):
        with patch("ui.screens.form_screen.ask_ticket_id", return_value="test-ticket"), \
             patch("ui.screens.form_screen.show_loading") as loading, \
             patch("ui.screens.form_screen.show_info"):
            self.screen._on_fetch_from_itsm()
            callbacks = loading.call_args.kwargs
            callbacks["on_done"](callbacks["worker"]())
        self.assertEqual(self.screen._collect_form_data(), {"name": "from ticket"})

    def test_validation_and_confirmation_still_precede_submission(self):
        with patch("ui.screens.form_screen.show_error") as error, \
             patch("ui.screens.form_screen.show_loading") as loading, \
             patch("ui.screens.form_screen.show_submit_confirm", return_value=False) as confirm:
            self.screen._on_submit()
            error.assert_called_once()
            confirm.assert_not_called()
            self.screen.apply_form_data({"name": "manual"})
            self.screen._on_submit()
            confirm.assert_called_once()
            loading.assert_not_called()
        self.screen.app.submit_service.submit.assert_not_called()

    def test_submit_success_without_execution_plan_callbacks(self):
        self.screen.apply_form_data({"name": "manual"})
        result = SimpleNamespace(success=True, message="done", raw_response={}, payload={"name": "manual"})
        self.screen.app.submit_service.submit.return_value = result
        with patch("ui.screens.form_screen.show_submit_confirm", return_value=True), \
             patch("ui.screens.form_screen.show_loading") as loading:
            self.screen._on_submit()
            callbacks = loading.call_args.kwargs
            callbacks["on_done"](callbacks["worker"]())
        self.screen.app.submit_service.submit.assert_called_once_with(
            self.screen._form, {"name": "manual"}, "test")
        self.screen.app.run_storage.save.assert_called_once()
        self.screen.app.navigate_to.assert_called_once()

    def test_submit_failures_show_errors_without_ai_diagnostics(self):
        self.screen.apply_form_data({"name": "manual"})
        with patch("ui.screens.form_screen.show_submit_confirm", return_value=True), \
             patch("ui.screens.form_screen.show_loading") as loading, \
             patch("ui.screens.form_screen.show_error") as error:
            self.screen._on_submit()
            callbacks = loading.call_args.kwargs
            callbacks["on_done"](SimpleNamespace(success=False, message="failed"))
            self.assertIn("failed", self.screen._status_var.get())
            callbacks["on_error"](RuntimeError("connection failed"))
            self.assertEqual(error.call_count, 2)
            self.assertIn("connection failed", self.screen._status_var.get())
        self.screen.app.navigate_to.assert_not_called()
        self.assertFalse(hasattr(self.screen, "_diagnose_submit_btn"))

    def test_json_preview_is_available_without_ai(self):
        self.screen.apply_form_data({"name": "manual"})
        with patch("ui.screens.form_screen.show_text_viewer") as viewer:
            self.screen._preview_payload()
        self.assertIn('"name": "manual"', viewer.call_args.args[2])


if __name__ == "__main__":
    unittest.main()
