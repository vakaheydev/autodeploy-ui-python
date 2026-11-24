import tkinter as tk
import unittest

from forms.base_form import BaseForm
from forms.fields import FieldDefinition, FieldType
from tests.plural_preview import PreviewForm, make_screen
from ui.widgets.field_factory import FieldFactory, _BlockWidget


class PluralControlsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root = tk.Tk()
        cls.root.withdraw()

    @classmethod
    def tearDownClass(cls):
        cls.root.destroy()

    def setUp(self):
        self.screen = make_screen(self.root)

    def tearDown(self):
        for child in self.root.winfo_children():
            child.destroy()

    def test_remove_middle_then_first_preserves_payload_and_widgets(self):
        screen = self.screen
        screen.apply_form_data({
            "service": {"name": "first", "path": "/first"},
            "service_2": {"name": "middle", "path": "/middle"},
            "service_3": {"name": "last", "path": "/last"},
        })
        last = screen._field_widgets["service_3"]
        group = screen._plural_groups["service"]
        # Invoke the actual buttons, including their callbacks after rekeying.
        group._rows["service_2"][1].invoke()
        self.assertIs(screen._field_widgets["service_2"], last)
        payload = screen._form.build_payload(screen._collect_form_data())
        self.assertEqual([v["name"] for v in payload["services"]], ["first", "last"])
        group._rows["service"][1].invoke()
        self.assertIs(screen._field_widgets["service"], last)
        self.assertEqual(screen._collect_form_data(), {"service": {"name": "last", "path": "/last"}})
        self.assertEqual(str(group._rows["service"][1]["state"]), "disabled")
        screen._remove_plural_field("service", "service", screen._field_containers["service"])
        self.assertEqual(group.keys, ["service"])
        self.assertEqual(screen._form.validate(screen._collect_form_data()), [])

    def test_bottom_add_button_and_limit_after_arbitrary_removal(self):
        screen = self.screen
        group = screen._plural_groups["service"]
        group._rows["service"][2].invoke()
        group._rows["service_2"][2].invoke()
        group._rows["service_3"][2].invoke()
        self.assertEqual(len(group.keys), 4)
        self.assertEqual(str(group._rows["service_4"][2]["state"]), "disabled")
        screen._add_plural_field("service")
        self.assertEqual(len(group.keys), 4)
        group._rows["service_2"][1].invoke()
        group._rows["service_3"][2].invoke()
        self.assertEqual(group.keys, ["service", "service_2", "service_3", "service_4"])
        self.assertEqual(screen._field_order, group.keys)
        for index, row in enumerate(group._rows.values()):
            self.assertEqual(row[2].cget("text"), "＋ Добавить блок «Сервис»")
            self.assertEqual(bool(row[2].winfo_manager()), index == 3)
            header_buttons = [child.cget("text") for child in row[1].master.winfo_children()
                              if isinstance(child, tk.Button)]
            self.assertEqual(header_buttons, ["× Удалить"])

    def test_nested_blocks_preserve_children_and_support_repeated_removal(self):
        field = FieldDefinition("item", "Элемент", FieldType.BLOCK, plural=True, plural_max=3,
            block_fields=[FieldDefinition("value", "Значение", FieldType.TEXT)])
        block = _BlockWidget(self.root, [field], FieldFactory(), lambda field: [])
        group = block._sub_plural_groups["item"]
        self.assertEqual(group._rows["item"][2].cget("text"), "＋ Добавить блок «Элемент»")
        for value in ("two", "three"):
            block._add_sub_plural("item")
            block._sub_widgets[group.keys[-1]].set({"value": value})
        last = block._sub_widgets["item_3"]
        group._rows["item_2"][1].invoke()
        group._rows["item"][1].invoke()
        self.assertIs(block._sub_widgets["item"], last)
        self.assertEqual(BaseForm.collect_plural(block.get(), "item"), [{"value": "three"}])
        self.assertEqual(str(group._rows["item"][1]["state"]), "disabled")
        group._rows["item"][2].invoke()
        self.assertEqual(group.keys, ["item", "item_2"])
        group._rows["item_2"][1].invoke()
        self.assertEqual(group.keys, ["item"])

    def test_restore_above_limit_terminates(self):
        self.screen.apply_form_data({"service_9": {"name": "ignored"}})
        self.assertEqual(len(self.screen._plural_groups["service"].keys), 4)

    def test_bottom_button_stays_below_rebuilt_widget(self):
        self.screen._rebuild_reference_widget(self.screen._form.fields[0])
        inner = self.screen._field_inner_frames["service"]
        bottom = self.screen._plural_groups["service"]._rows["service"][2]
        self.assertIs(inner.pack_slaves()[-1], bottom)

    def test_conditional_group_remains_together_after_first_removal(self):
        class ConditionalForm(PreviewForm):
            form_id = "test.conditional_plural"
            fields = [
                FieldDefinition("visible", "Visible", FieldType.CHECKBOX, default=True),
                FieldDefinition("items", "Items", FieldType.TEXT, plural=True,
                                condition=lambda values: values.get("visible")),
                FieldDefinition("tail", "Tail", FieldType.TEXT),
            ]
        screen = make_screen(self.root, ConditionalForm())
        screen._add_plural_field("items")
        group = screen._plural_groups["items"]
        group._rows["items"][1].invoke()
        screen._add_plural_field("items")
        for visible in (False, True):
            screen._field_widgets["visible"].set_and_notify(visible)
            self.assertTrue(all(bool(screen._field_containers[k].winfo_manager()) == visible
                                for k in group.keys))
        self.assertEqual(screen._field_order, ["visible", "items", "items_2", "tail"])


if __name__ == "__main__":
    unittest.main()
