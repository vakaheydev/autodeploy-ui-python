from __future__ import annotations

import zipfile
from pathlib import Path

import pytest

from scripts import update_from_zip


def _archive(path: Path, entries: dict[str, str]) -> Path:
    with zipfile.ZipFile(path, "w") as archive:
        for name, content in entries.items():
            archive.writestr(name, content)
    return path


def test_replaces_tree_and_preserves_env(tmp_path: Path) -> None:
    target = tmp_path / "gravitee-autodeploy"
    target.mkdir()
    (target / ".env").write_text("TOKEN=corporate-secret\n", encoding="utf-8")
    (target / "obsolete.txt").write_text("old", encoding="utf-8")
    archive = _archive(
        tmp_path / "source.zip",
        {
            "repository-branch/pyproject.toml": "[project]\n",
            "repository-branch/webapp/__init__.py": "",
            "repository-branch/current.txt": "new",
            "repository-branch/.env": "TOKEN=archive-value\n",
        },
    )

    backup = update_from_zip.replace_directory_from_zip(archive, target)

    assert backup is None
    assert (target / ".env").read_text(encoding="utf-8") == "TOKEN=corporate-secret\n"
    assert (target / "current.txt").read_text(encoding="utf-8") == "new"
    assert not (target / "obsolete.txt").exists()


def test_rejects_zip_slip_without_changing_target(tmp_path: Path) -> None:
    target = tmp_path / "gravitee-autodeploy"
    target.mkdir()
    (target / ".env").write_text("TOKEN=keep\n", encoding="utf-8")
    (target / "old.txt").write_text("old", encoding="utf-8")
    archive = _archive(
        tmp_path / "unsafe.zip",
        {
            "../outside.txt": "bad",
            "repository-branch/pyproject.toml": "[project]\n",
            "repository-branch/webapp/__init__.py": "",
        },
    )

    with pytest.raises(update_from_zip.UpdateError, match="небезопасный путь"):
        update_from_zip.replace_directory_from_zip(archive, target)

    assert (target / ".env").read_text(encoding="utf-8") == "TOKEN=keep\n"
    assert (target / "old.txt").read_text(encoding="utf-8") == "old"
    assert not (tmp_path / "outside.txt").exists()


def test_rejects_wrong_archive_without_changing_target(tmp_path: Path) -> None:
    target = tmp_path / "gravitee-autodeploy"
    target.mkdir()
    (target / "old.txt").write_text("old", encoding="utf-8")
    archive = _archive(
        tmp_path / "wrong.zip",
        {"another-project/readme.txt": "not autodeploy"},
    )

    with pytest.raises(update_from_zip.UpdateError, match="не похож"):
        update_from_zip.replace_directory_from_zip(archive, target)

    assert (target / "old.txt").read_text(encoding="utf-8") == "old"
