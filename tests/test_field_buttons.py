"""Portable contract tests; this file is identical in master and web-platform."""
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
import tkinter as tk

from forms.base_form import BaseForm, ServerActionResult, ServerDialogActionResult
from forms.field_actions import FieldAction, FieldActionDialog, FieldDialogAction
from forms.fields import FieldDefinition, FieldType, ReferenceConfig
from forms.result_config import ResultStatus
from forms.registry import FormRegistry
from ui.field_actions import DesktopFieldActions
from ui.screens.form_screen import FormScreen
from ui.widgets.field_factory import FieldFactory


class FieldActionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            cls.root = tk.Tk()
            cls.root.withdraw()
        except tk.TclError as exc:
            raise unittest.SkipTest(str(exc))

    @classmethod
    def tearDownClass(cls):
        cls.root.destroy()

    def setUp(self):
        self.frame = tk.Frame(self.root)
        self.app = SimpleNamespace(
            current_environment=tk.StringVar(self.root, value="test"),
            http_client=Mock(), reference_resolver=Mock(), reference_cache=Mock(),
            itsm_service=object(), tfs_service=object(), gravitee_service=object(),
            go_back=lambda: None, go_home=lambda: None,
            release_execution_plan_step=lambda *args, **kwargs: None,
        )
        self.app.reference_resolver.resolve.return_value = [{"id": "b", "name": "Bee"}]
        self.screen = SimpleNamespace(app=self.app, _field_widgets={})
        self.screen._collect_form_data = lambda: {k: w.get() for k, w in self.screen._field_widgets.items()}
        self.factory = FieldFactory(lambda b, f, w: DesktopFieldActions(self.screen, f, w).run(b))

    def tearDown(self):
        for child in self.root.winfo_children():
            child.destroy()

    def make(self, kind, handler, **kwargs):
        field = FieldDefinition("target", "Target", kind,
            actions=(FieldAction("fill", "Fill", handler=handler),), **kwargs)
        widget = self.factory.create(self.frame, field, [{"id": "b", "name": "Bee"}])
        self.screen._field_widgets["target"] = widget
        return field, widget

    def click(self, widget, label="Fill"):
        for child in widget.winfo_children():
            if child.winfo_class() == "TButton" and child.cget("text") == label:
                child.invoke()
                return True
            if self.click(child, label):
                return True
        return False

    def test_returns_all_types_and_notifies_once(self):
        for kind, value in ((FieldType.TEXT, ""), (FieldType.TEXTAREA, "text"),
                            (FieldType.FILE, "file"), (FieldType.NUMBER, 0), (FieldType.NUMBER, -1.5),
                            (FieldType.CHECKBOX, False), (FieldType.SELECT, "b"),
                            (FieldType.MULTISELECT, []), (FieldType.BLOCK, {"child": "yes"})):
            with self.subTest(kind=kind):
                field, widget = self.make(kind, lambda ctx, v=value: v,
                    reference=ReferenceConfig("local", "unused"),
                    block_fields=[FieldDefinition("child", "Child", FieldType.TEXT)])
                changed = Mock()
                widget.bind_change(changed)
                DesktopFieldActions(self.screen, field, widget).run(field.actions[0])
                self.assertEqual(widget.get(), value)
                changed.assert_called_once_with()
                widget.widget.destroy()

    def test_none_error_and_exception_do_not_apply_staged_changes(self):
        def error(ctx):
            ctx.set_value("bad")
            return ServerActionResult(status=ResultStatus.ERROR, message="failed")
        def raises(ctx):
            ctx.set_value("bad")
            raise ValueError("failed")
        for handler in (lambda ctx: None, error, raises):
            field, widget = self.make(FieldType.TEXT, handler, default="keep")
            with patch("ui.field_actions.dialogs.show_error"):
                try:
                    DesktopFieldActions(self.screen, field, widget).run(field.actions[0])
                except ValueError:
                    self.assertIs(handler, raises)
            self.assertEqual(widget.get(), "keep")
            widget.widget.destroy()

    def test_context_and_nested_plural_target(self):
        seen = []
        def handler(ctx):
            seen.append(ctx)
            self.assertIs(ctx.services.tfs, self.app.tfs_service)
            self.assertIs(ctx.http, self.app.http_client)
            self.assertEqual(ctx.load_reference(ReferenceConfig("local", "x"))[0]["id"], "b")
            ctx.set_value("chosen")
        child = FieldDefinition("value", "Value", FieldType.TEXT, actions=(FieldAction("fill", "Fill", handler),))
        block = FieldDefinition("block", "Block", FieldType.BLOCK, block_fields=[child], plural=True)
        first = self.factory.create(self.frame, block)
        second = self.factory.create(self.frame, block)
        self.screen._field_widgets = {"block": first, "block_2": second}
        self.click(second.widget)
        self.assertEqual(first.get(), {"value": ""})
        self.assertEqual(second.get(), {"value": "chosen"})
        self.assertEqual(seen[0].field_path, "block_2.value")
        self.assertIn("block", seen[0].form_values)

    def test_declarative_dialog_selection_and_cancel(self):
        field, widget = self.make(FieldType.TEXT, lambda _: None, default="keep")
        adapter = DesktopFieldActions(self.screen, field, widget)
        # Real Tk parent; all other screen capabilities remain shared.
        adapter.screen = self.frame
        self.frame.app = self.app
        self.frame._field_widgets = self.screen._field_widgets
        self.frame._collect_form_data = self.screen._collect_form_data
        dialog = FieldActionDialog("Choose", [
            FieldDefinition("choice", "Choice", FieldType.SELECT, reference=ReferenceConfig("local", "x")),
        ], [FieldDialogAction("apply", "Apply", lambda ctx: ctx.get_selected_items("choice")[0]["name"])],
            initial_values={"choice": "b"})
        adapter.open_dialog(dialog)
        self.click(adapter.window, "Apply")
        self.assertEqual(widget.get(), "Bee")
        adapter.dialog_widget = None
        adapter.open_dialog(dialog)
        self.click(adapter.window, "Отмена")
        self.assertEqual(widget.get(), "Bee")

    def test_real_screen_plural_and_conditions(self):
        class Demo(BaseForm):
            form_id, title, category = "test.portable-actions", "Actions", "other"
            fields = [
                FieldDefinition("source", "Source", FieldType.TEXT, plural=True,
                    actions=(FieldAction("fill", "Fill", lambda ctx: "chosen"),)),
                FieldDefinition("dependent", "Dependent", FieldType.TEXT,
                    condition=lambda values: values.get("source") == "chosen"),
            ]
            def build_payload(self, values): return values
            def get_submit_endpoint(self, environment): return ""
        FormRegistry().register(Demo())
        screen = FormScreen(self.root, self.app, form_id=Demo.form_id)
        screen.pack()
        screen._add_plural_field("source")
        self.click(screen._field_widgets["source_2"].widget)
        self.assertEqual(screen._collect_form_data(), {"source": "", "source_2": "chosen"})
        self.click(screen._field_widgets["source"].widget)
        self.assertIn("dependent", screen._collect_form_data())
        screen.destroy()

    def test_confirmation_readonly_context_and_stale_environment(self):
        called = Mock(return_value="changed")
        field, widget = self.make(FieldType.TEXT, called, default="keep")
        adapter = DesktopFieldActions(self.screen, field, widget)
        action = FieldAction("confirmed", "Confirm", called, confirmation_text="Apply?")
        with patch("ui.field_actions.dialogs.show_confirm", return_value=False):
            adapter.run(action)
        called.assert_not_called()
        ctx, _ = adapter.context()
        with self.assertRaises(ValueError):
            ctx.set_value("bad")
        self.app.current_environment.set("other")
        with self.assertRaises(ValueError):
            adapter.run(field.actions[0])
        self.assertEqual(widget.get(), "keep")

    def test_block_reference_dependencies_only_pass_declared_values(self):
        from forms.fields import ReferenceDependency
        loader = Mock(return_value=[{"id": "b", "name": "Bee"}])
        block = FieldDefinition("block", "Block", FieldType.BLOCK, block_fields=[
            FieldDefinition("source", "Source", FieldType.TEXT, default="first"),
            FieldDefinition("secret", "Secret", FieldType.TEXT, default="do-not-pass"),
            FieldDefinition("choice", "Choice", FieldType.SELECT,
                reference=ReferenceConfig("http", "choices"),
                reference_dependencies=(ReferenceDependency("source", parameter="parent"),)),
        ])
        widget = self.factory.create(self.frame, block, ref_loader=loader)
        widget.children["source"].set_and_notify("second")
        self.assertEqual(loader.call_args.args[1], {"parent": "second"})


if __name__ == "__main__":
    unittest.main()
