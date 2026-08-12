from __future__ import annotations

import asyncio
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from enterprise_rag.application.dto.desktop_settings import DesktopSettingsDto
from enterprise_rag.domain.errors import ApplicationError
from enterprise_rag.infrastructure.config.filesystem_desktop_settings_repository import (
    FilesystemDesktopSettingsRepository,
)


def _defaults(root: Path) -> DesktopSettingsDto:
    return DesktopSettingsDto(
        settings_revision=0,
        source_root=str(root / "source"),
        output_root=str(root / "output"),
        model_id="mlx-community/Qwen3.6-27B-4bit",
        model_revision="a" * 40,
        context_tokens=16_384,
        max_output_tokens=4_096,
        additional_system_prompt="",
        max_task_attempts=3,
        offline_mode=True,
        notify_on_completion=True,
    )


class FilesystemDesktopSettingsRepositoryTest(unittest.TestCase):
    def test_loads_defaults_then_atomically_persists_revisioned_settings(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            defaults = _defaults(root)
            repository = FilesystemDesktopSettingsRepository(root / "var", defaults)
            self.assertEqual(asyncio.run(repository.load()), defaults)
            desired = replace(defaults, additional_system_prompt="명령을 보존한다.")
            updated = asyncio.run(repository.save(0, desired))
            self.assertEqual(updated.settings_revision, 1)
            reopened = FilesystemDesktopSettingsRepository(root / "var", defaults)
            self.assertEqual(asyncio.run(reopened.load()), updated)

    def test_rejects_stale_revision_and_corrupt_settings(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            defaults = _defaults(root)
            repository = FilesystemDesktopSettingsRepository(root / "var", defaults)
            updated = asyncio.run(repository.save(0, defaults))
            with self.assertRaises(ApplicationError) as captured:
                asyncio.run(repository.save(0, replace(updated, offline_mode=False)))
            self.assertEqual(captured.exception.code, "SETTINGS_REVISION_CONFLICT")

            settings_path = root / "var/config/desktop-settings.json"
            settings_path.write_text("not-json", encoding="utf-8")
            with self.assertRaises(ApplicationError) as captured:
                asyncio.run(repository.load())
            self.assertEqual(captured.exception.code, "DESKTOP_SETTINGS_INVALID")

    def test_rejects_workspace_that_contains_internal_checkpoint_root(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            defaults = _defaults(root)
            repository = FilesystemDesktopSettingsRepository(root / "var", defaults)
            unsafe = replace(defaults, output_root=str(root / "var/published"))
            with self.assertRaises(ApplicationError) as captured:
                asyncio.run(repository.save(0, unsafe))
            self.assertEqual(captured.exception.code, "DESKTOP_SETTINGS_INVALID")


if __name__ == "__main__":
    unittest.main()
