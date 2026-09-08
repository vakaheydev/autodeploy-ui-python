"""Validate local Markdown links and documentation separation.

External URLs are intentionally not requested: the check must run offline in
corporate CI. Anchor fragments are ignored because Markdown renderers differ.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path
from urllib.parse import unquote, urlsplit


ROOT = Path(__file__).resolve().parent.parent
CORP_ROOT = ROOT / "docs" / "corp"
MARKDOWN_LINK = re.compile(r"(?<!!)\[[^\]]+\]\(([^)]+)\)")
IGNORED_PARTS = frozenset({
    ".git", ".pytest_cache", ".venv", "build", "dist", "node_modules"
})
REMOVED_DOCUMENTS = {
    "GUIDE.md",
    "OPENCODE_AUTOFILL.md",
    "CORPORATE_MIGRATION.md",
    "FIRST_CORPORATE_FORM_MIGRATION.md",
    "CORPORATE_ENVIRONMENT_HOOK.md",
}


def target_from(raw: str) -> str:
    value = raw.strip()
    if value.startswith("<") and value.endswith(">"):
        value = value[1:-1]
    # Optional Markdown title follows a whitespace; project paths contain no
    # spaces, so keeping the first token is deterministic for this repository.
    return value.split(maxsplit=1)[0]


def main() -> int:
    failures: list[str] = []
    documents = sorted(
        path for path in ROOT.rglob("*.md")
        if not IGNORED_PARTS.intersection(path.relative_to(ROOT).parts)
    )
    for document in documents:
        text = document.read_text(encoding="utf-8")
        for line_number, line in enumerate(text.splitlines(), 1):
            for match in MARKDOWN_LINK.finditer(line):
                raw = target_from(match.group(1))
                parsed = urlsplit(raw)
                if parsed.scheme or raw.startswith(("#", "mailto:")):
                    continue
                relative = unquote(parsed.path).replace("\\", "/")
                if not relative:
                    continue
                if Path(relative).name in REMOVED_DOCUMENTS:
                    failures.append(
                        f"{document.relative_to(ROOT)}:{line_number}: "
                        f"ссылка на удалённый migration-документ {relative}"
                    )
                    continue
                target = (document.parent / relative).resolve()
                try:
                    target.relative_to(ROOT)
                except ValueError:
                    failures.append(
                        f"{document.relative_to(ROOT)}:{line_number}: "
                        f"ссылка выходит за репозиторий: {relative}"
                    )
                    continue
                if CORP_ROOT in document.parents:
                    try:
                        target.relative_to(CORP_ROOT)
                    except ValueError:
                        failures.append(
                            f"{document.relative_to(ROOT)}:{line_number}: "
                            f"corporate handbook не самодостаточен: {relative}"
                        )
                        continue
                if not target.exists():
                    failures.append(
                        f"{document.relative_to(ROOT)}:{line_number}: "
                        f"не найдено: {relative}"
                    )

    if failures:
        print("Ошибки документации:", file=sys.stderr)
        print("\n".join(f"- {item}" for item in failures), file=sys.stderr)
        return 1
    print(f"Documentation OK: {len(documents)} Markdown files")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
