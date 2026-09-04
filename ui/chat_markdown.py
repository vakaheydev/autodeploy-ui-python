"""Small dependency-free Markdown renderer for Tkinter chat messages.

The parser deliberately implements the subset that language models commonly use
in chat: headings, emphasis, inline/fenced code, links, quotes and lists.  It
keeps the original message untouched; only the Text widget presentation changes.
"""
from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Iterable


@dataclass(frozen=True)
class MarkdownSpan:
    text: str
    tags: tuple[str, ...] = ()


_FENCE_RE = re.compile(r"^\s*```(?:[^`]*)?\s*$")
_HEADING_RE = re.compile(r"^(#{1,3})\s+(.+?)\s*$")
_QUOTE_RE = re.compile(r"^\s*>\s?(.*)$")
_BULLET_RE = re.compile(r"^(\s*)[-+*]\s+(.+)$")
_ORDERED_RE = re.compile(r"^(\s*)(\d+)[.)]\s+(.+)$")
_RULE_RE = re.compile(r"^\s*(?:-{3,}|\*{3,}|_{3,})\s*$")


def parse_markdown(text: str) -> tuple[MarkdownSpan, ...]:
    """Convert chat Markdown into text spans carrying Tk tag names."""
    normalized = str(text).replace("\r\n", "\n").replace("\r", "\n")
    spans: list[MarkdownSpan] = []
    in_code_block = False

    for raw_line in normalized.splitlines(keepends=True):
        has_newline = raw_line.endswith("\n")
        line = raw_line[:-1] if has_newline else raw_line
        suffix = "\n" if has_newline else ""

        if _FENCE_RE.match(line):
            in_code_block = not in_code_block
            continue
        if in_code_block:
            spans.append(MarkdownSpan(line + suffix, ("md_code_block",)))
            continue

        heading = _HEADING_RE.match(line)
        if heading:
            level = min(len(heading.group(1)), 3)
            spans.extend(_inline(heading.group(2), (f"md_heading_{level}",)))
            _append(spans, suffix, (f"md_heading_{level}",))
            continue

        quote = _QUOTE_RE.match(line)
        if quote:
            _append(spans, "│  ", ("md_quote_marker",))
            spans.extend(_inline(quote.group(1), ("md_quote",)))
            _append(spans, suffix, ("md_quote",))
            continue

        bullet = _BULLET_RE.match(line)
        if bullet:
            indent = _list_indent(bullet.group(1))
            _append(spans, indent + "•  ", ("md_list_marker",))
            spans.extend(_inline(bullet.group(2)))
            _append(spans, suffix)
            continue

        ordered = _ORDERED_RE.match(line)
        if ordered:
            indent = _list_indent(ordered.group(1))
            _append(
                spans,
                indent + ordered.group(2) + ".  ",
                ("md_list_marker",),
            )
            spans.extend(_inline(ordered.group(3)))
            _append(spans, suffix)
            continue

        if _RULE_RE.match(line):
            _append(spans, "────────────────────────" + suffix, ("md_rule",))
            continue

        spans.extend(_inline(line))
        _append(spans, suffix)

    # splitlines() yields no item for the empty string.
    if not normalized:
        return ()
    return tuple(spans)


def insert_markdown(text_widget: object, text: str, base_tag: str) -> None:
    """Insert parsed Markdown into a Tk Text-like widget."""
    for span in parse_markdown(text):
        if span.text:
            text_widget.insert("end", span.text, (base_tag, *span.tags))


def _inline(text: str, inherited: tuple[str, ...] = ()) -> list[MarkdownSpan]:
    spans: list[MarkdownSpan] = []
    index = 0
    plain_start = 0

    while index < len(text):
        token = _inline_token(text, index)
        if token is None:
            index += 1
            continue
        end, value, tags = token
        if plain_start < index:
            _append(spans, text[plain_start:index], inherited)
        _append(spans, value, inherited + tags)
        index = end
        plain_start = end

    if plain_start < len(text):
        _append(spans, text[plain_start:], inherited)
    return spans


def _inline_token(
    text: str,
    start: int,
) -> tuple[int, str, tuple[str, ...]] | None:
    if text[start] == "`":
        end = text.find("`", start + 1)
        if end > start + 1:
            return end + 1, text[start + 1:end], ("md_code",)

    for marker, tag in (("**", "md_bold"), ("__", "md_bold")):
        if text.startswith(marker, start):
            end = text.find(marker, start + len(marker))
            if end > start + len(marker):
                return end + len(marker), text[start + len(marker):end], (tag,)

    if text[start] == "[":
        label_end = text.find("](", start + 1)
        if label_end > start + 1:
            url_end = text.find(")", label_end + 2)
            if url_end > label_end + 2:
                label = text[start + 1:label_end]
                url = text[label_end + 2:url_end]
                return url_end + 1, f"{label} ({url})", ("md_link",)

    marker = text[start]
    if marker in {"*", "_"} and not text.startswith(marker * 2, start):
        # An underscore inside an identifier (context_path) is not emphasis.
        if marker == "_" and start > 0 and text[start - 1].isalnum():
            return None
        end = text.find(marker, start + 1)
        if end > start + 1:
            if marker == "_" and end + 1 < len(text) and text[end + 1].isalnum():
                return None
            return end + 1, text[start + 1:end], ("md_italic",)
    return None


def _list_indent(whitespace: str) -> str:
    # Four source spaces become one readable visual nesting step.
    return "  " * max(0, (len(whitespace.expandtabs(4)) + 1) // 2)


def _append(
    spans: list[MarkdownSpan],
    text: str,
    tags: Iterable[str] = (),
) -> None:
    if not text:
        return
    normalized_tags = tuple(tags)
    if spans and spans[-1].tags == normalized_tags:
        previous = spans[-1]
        spans[-1] = MarkdownSpan(previous.text + text, previous.tags)
    else:
        spans.append(MarkdownSpan(text, normalized_tags))
