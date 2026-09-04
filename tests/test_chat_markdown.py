from __future__ import annotations

import unittest

from ui.chat_markdown import insert_markdown, parse_markdown


class _TextRecorder:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, tuple[str, ...]]] = []

    def insert(self, index: str, text: str, tags: tuple[str, ...]) -> None:
        self.calls.append((index, text, tags))


class ChatMarkdownTests(unittest.TestCase):
    def test_common_model_markdown_is_rendered_without_markers(self) -> None:
        spans = parse_markdown(
            "## Результат\n"
            "**API создан** и *проверен*, путь — `/test/workflow`.\n"
            "- первый пункт\n"
            "1. второй пункт"
        )

        visible = "".join(span.text for span in spans)
        self.assertNotIn("**", visible)
        self.assertNotIn("##", visible)
        self.assertIn("Результат", visible)
        self.assertIn("•  первый пункт", visible)
        self.assertIn("1.  второй пункт", visible)
        self.assertTrue(
            any(span.text == "API создан" and "md_bold" in span.tags for span in spans)
        )
        self.assertTrue(
            any(span.text == "проверен" and "md_italic" in span.tags for span in spans)
        )
        self.assertTrue(
            any(
                span.text == "/test/workflow" and "md_code" in span.tags
                for span in spans
            )
        )

    def test_identifiers_with_underscores_are_not_italic(self) -> None:
        spans = parse_markdown("context_path и endpoint_header_host")

        self.assertEqual(
            "".join(span.text for span in spans),
            "context_path и endpoint_header_host",
        )
        self.assertFalse(any("md_italic" in span.tags for span in spans))

    def test_fenced_code_hides_fences_and_preserves_code(self) -> None:
        spans = parse_markdown('```json\n{"name": "Test.Ck"}\n```')

        self.assertEqual("".join(span.text for span in spans), '{"name": "Test.Ck"}\n')
        self.assertTrue(all("md_code_block" in span.tags for span in spans))

    def test_link_is_readable_without_raw_markdown(self) -> None:
        spans = parse_markdown("[OpenCode](http://127.0.0.1:4096)")

        self.assertEqual(
            "".join(span.text for span in spans),
            "OpenCode (http://127.0.0.1:4096)",
        )
        self.assertIn("md_link", spans[0].tags)

    def test_widget_receives_base_and_markdown_tags(self) -> None:
        widget = _TextRecorder()

        insert_markdown(widget, "**готово**", "assistant")

        self.assertEqual(
            widget.calls,
            [("end", "готово", ("assistant", "md_bold"))],
        )


if __name__ == "__main__":
    unittest.main()
