from __future__ import annotations

import unittest
from types import SimpleNamespace

try:
    import tkinter  # noqa: F401
except ImportError:  # pragma: no cover - зависит от системного Python/Tk
    tkinter = None  # type: ignore[assignment]

if tkinter is not None:
    from ui.ai_assistant import AIAssistantDialog
    from ui.screens.form_screen import FormScreen


class _ScrollTarget:
    def __init__(self) -> None:
        self.calls: list[tuple[int, str]] = []

    def yview_scroll(self, units: int, mode: str) -> None:
        self.calls.append((units, mode))


class _Widget:
    def __init__(self, top: str, *, master: object | None = None) -> None:
        self._top = top
        self.master = master

    def winfo_toplevel(self) -> str:
        return self._top


@unittest.skipIf(tkinter is None, "системный Python собран без Tkinter")
class AssistantScrollIsolationTests(unittest.TestCase):
    def test_foreign_toplevel_wheel_never_scrolls_main_form(self) -> None:
        main_scroll = _ScrollTarget()
        screen = SimpleNamespace(
            winfo_toplevel=lambda: ".main",
            _scroll_canvas=main_scroll,
        )
        event = SimpleNamespace(widget=_Widget(".assistant"), delta=-120)

        result = FormScreen._route_mousewheel(screen, event)

        self.assertEqual(result, "break")
        self.assertEqual(main_scroll.calls, [])

    def test_form_owned_nested_scroll_target_receives_wheel(self) -> None:
        main_scroll = _ScrollTarget()
        nested_scroll = _ScrollTarget()
        owner = _Widget(".main")
        owner._scroll_target = nested_scroll  # type: ignore[attr-defined]
        child = _Widget(".main", master=owner)
        screen = SimpleNamespace(
            winfo_toplevel=lambda: ".main",
            _scroll_canvas=main_scroll,
        )

        result = FormScreen._route_mousewheel(
            screen,
            SimpleNamespace(widget=child, delta=120),
        )

        self.assertEqual(result, "break")
        self.assertEqual(nested_scroll.calls, [(-1, "units")])
        self.assertEqual(main_scroll.calls, [])

    def test_assistant_text_scroll_handles_windows_and_linux_events(self) -> None:
        target = _ScrollTarget()

        self.assertEqual(
            AIAssistantDialog._scroll_widget(
                target,  # type: ignore[arg-type]
                SimpleNamespace(delta=-120, num=None),
            ),
            "break",
        )
        AIAssistantDialog._scroll_widget(
            target,  # type: ignore[arg-type]
            SimpleNamespace(delta=0, num=4),
        )

        self.assertEqual(target.calls, [(1, "units"), (-1, "units")])


if __name__ == "__main__":
    unittest.main()
