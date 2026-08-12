from __future__ import annotations

import asyncio
import unittest
from dataclasses import replace

from enterprise_rag.application.dto.desktop_settings import DesktopSettingsDto
from enterprise_rag.application.use_cases.manage_desktop_settings import (
    GetDesktopSettings,
    UpdateDesktopSettings,
)
from enterprise_rag.domain.errors import ApplicationError


def _settings(**changes: object) -> DesktopSettingsDto:
    values: dict[str, object] = {
        "settings_revision": 0,
        "source_root": "/workspace/source",
        "output_root": "/workspace/output",
        "model_id": "mlx-community/Qwen3.6-27B-4bit",
        "model_revision": "a" * 40,
        "context_tokens": 16_384,
        "max_output_tokens": 4_096,
        "additional_system_prompt": "운영 절차를 우선한다.",
        "max_task_attempts": 3,
        "offline_mode": True,
        "notify_on_completion": True,
    }
    values.update(changes)
    return DesktopSettingsDto(**values)  # type: ignore[arg-type]


class _Repository:
    def __init__(self, settings: DesktopSettingsDto) -> None:
        self.settings = settings

    async def load(self) -> DesktopSettingsDto:
        return self.settings

    async def save(
        self,
        expected_revision: int,
        settings: DesktopSettingsDto,
    ) -> DesktopSettingsDto:
        self.settings = replace(settings, settings_revision=expected_revision + 1)
        return self.settings


class DesktopSettingsTest(unittest.TestCase):
    def test_gets_and_updates_settings_through_application_use_cases(self) -> None:
        repository = _Repository(_settings())
        self.assertEqual(
            asyncio.run(GetDesktopSettings(repository).execute()),
            repository.settings,
        )
        desired = replace(repository.settings, additional_system_prompt="보안 경고를 보존한다.")
        updated = asyncio.run(UpdateDesktopSettings(repository).execute(0, desired))
        self.assertEqual(updated.settings_revision, 1)
        self.assertEqual(updated.additional_system_prompt, "보안 경고를 보존한다.")

    def test_update_rejects_stale_dto_before_repository_write(self) -> None:
        repository = _Repository(_settings())
        with self.assertRaises(ApplicationError) as captured:
            asyncio.run(
                UpdateDesktopSettings(repository).execute(
                    1,
                    repository.settings,
                )
            )
        self.assertEqual(captured.exception.code, "SETTINGS_REVISION_CONFLICT")

    def test_rejects_invalid_paths_model_budget_prompt_and_attempts(self) -> None:
        cases = (
            {"settings_revision": -1},
            {"source_root": "relative/source"},
            {"output_root": "/workspace/source/nested"},
            {"model_id": "invalid"},
            {"model_revision": "main"},
            {"context_tokens": 4_095},
            {"context_tokens": 5_000},
            {"max_output_tokens": 256},
            {"max_output_tokens": 16_000},
            {"additional_system_prompt": "x" * 20_001},
            {"max_task_attempts": 0},
            {"max_task_attempts": 4},
        )
        for changes in cases:
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                _settings(**changes)

    def test_normalizes_absolute_workspace_paths(self) -> None:
        settings = _settings(
            source_root="/workspace/input/../source",
            output_root="/workspace/result/../output",
        )
        self.assertEqual(settings.source_root, "/workspace/source")
        self.assertEqual(settings.output_root, "/workspace/output")


if __name__ == "__main__":
    unittest.main()
