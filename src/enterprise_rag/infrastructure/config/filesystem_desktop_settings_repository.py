from __future__ import annotations

import asyncio
import fcntl
import json
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import replace
from pathlib import Path
from typing import Any

from enterprise_rag.application.dto.desktop_settings import DesktopSettingsDto
from enterprise_rag.domain.errors import ApplicationError, revision_error
from enterprise_rag.infrastructure.workspace.file_io import atomic_write_json
from enterprise_rag.infrastructure.workspace.path_security import is_link_or_reparse


class FilesystemDesktopSettingsRepository:
    def __init__(self, var_root: Path, defaults: DesktopSettingsDto) -> None:
        self._defaults = defaults
        try:
            var_root.mkdir(parents=True, exist_ok=True)
            resolved_var = var_root.expanduser().resolve(strict=True)
            if is_link_or_reparse(resolved_var):
                raise revision_error("LINK_NOT_ALLOWED")
            self._var_root = resolved_var
            self._assert_workspace_disjoint(defaults)
            self._config_root = resolved_var / "config"
            self._config_root.mkdir(exist_ok=True)
            if is_link_or_reparse(self._config_root):
                raise revision_error("LINK_NOT_ALLOWED")
            self._path = self._config_root / "desktop-settings.json"
            self._lock_path = self._config_root / ".desktop-settings.lock"
        except ApplicationError:
            raise
        except OSError as error:
            raise revision_error("IO_FAILURE") from error

    async def load(self) -> DesktopSettingsDto:
        return await asyncio.to_thread(self._load_locked)

    async def save(
        self,
        expected_revision: int,
        settings: DesktopSettingsDto,
    ) -> DesktopSettingsDto:
        return await asyncio.to_thread(self._save_locked, expected_revision, settings)

    def _load_locked(self) -> DesktopSettingsDto:
        try:
            with self._locked() as _:
                return self._load_unlocked()
        except ApplicationError:
            raise
        except OSError as error:
            raise revision_error("IO_FAILURE") from error

    def _save_locked(
        self,
        expected_revision: int,
        settings: DesktopSettingsDto,
    ) -> DesktopSettingsDto:
        try:
            with self._locked() as _:
                current = self._load_unlocked()
                if (
                    expected_revision != current.settings_revision
                    or settings.settings_revision != expected_revision
                ):
                    raise revision_error("SETTINGS_REVISION_CONFLICT")
                self._assert_workspace_disjoint(settings)
                updated = replace(settings, settings_revision=expected_revision + 1)
                atomic_write_json(self._path, self._serialize(updated))
                return updated
        except ApplicationError:
            raise
        except (OSError, TypeError, ValueError) as error:
            raise revision_error("IO_FAILURE") from error

    def _load_unlocked(self) -> DesktopSettingsDto:
        if not self._path.exists():
            return self._defaults
        if is_link_or_reparse(self._path):
            raise revision_error("LINK_NOT_ALLOWED")
        try:
            value = json.loads(self._path.read_text(encoding="utf-8"))
            settings = self._deserialize(value)
            self._assert_workspace_disjoint(settings)
            return settings
        except ApplicationError:
            raise
        except (OSError, UnicodeDecodeError, json.JSONDecodeError, KeyError, ValueError) as error:
            raise revision_error("DESKTOP_SETTINGS_INVALID") from error

    @contextmanager
    def _locked(self) -> Iterator[None]:
        stream = self._lock_path.open("a+", encoding="utf-8")
        acquired = False
        try:
            fcntl.flock(stream.fileno(), fcntl.LOCK_EX)
            acquired = True
            yield
        finally:
            if acquired:
                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)
            stream.close()

    def _assert_workspace_disjoint(self, settings: DesktopSettingsDto) -> None:
        for selected in (Path(settings.source_root), Path(settings.output_root)):
            try:
                selected.relative_to(self._var_root)
                overlaps = True
            except ValueError:
                try:
                    self._var_root.relative_to(selected)
                    overlaps = True
                except ValueError:
                    overlaps = False
            if overlaps:
                raise revision_error("DESKTOP_SETTINGS_INVALID")

    @staticmethod
    def _serialize(settings: DesktopSettingsDto) -> dict[str, object]:
        return {
            "schema_version": 1,
            "settings_revision": settings.settings_revision,
            "source_root": settings.source_root,
            "output_root": settings.output_root,
            "model_id": settings.model_id,
            "model_revision": settings.model_revision,
            "context_tokens": settings.context_tokens,
            "max_output_tokens": settings.max_output_tokens,
            "additional_system_prompt": settings.additional_system_prompt,
            "max_task_attempts": settings.max_task_attempts,
            "offline_mode": settings.offline_mode,
            "notify_on_completion": settings.notify_on_completion,
        }

    @classmethod
    def _deserialize(cls, value: Any) -> DesktopSettingsDto:
        if not isinstance(value, dict) or value.get("schema_version") != 1:
            raise ValueError("invalid desktop settings schema")
        return DesktopSettingsDto(
            settings_revision=cls._integer(value["settings_revision"]),
            source_root=cls._string(value["source_root"]),
            output_root=cls._string(value["output_root"]),
            model_id=cls._string(value["model_id"]),
            model_revision=cls._string(value["model_revision"]),
            context_tokens=cls._integer(value["context_tokens"]),
            max_output_tokens=cls._integer(value["max_output_tokens"]),
            additional_system_prompt=cls._string(value["additional_system_prompt"]),
            max_task_attempts=cls._integer(value["max_task_attempts"]),
            offline_mode=cls._boolean(value["offline_mode"]),
            notify_on_completion=cls._boolean(value["notify_on_completion"]),
        )

    @staticmethod
    def _integer(value: Any) -> int:
        if isinstance(value, bool) or not isinstance(value, int):
            raise ValueError("expected integer")
        return int(value)

    @staticmethod
    def _string(value: Any) -> str:
        if not isinstance(value, str):
            raise ValueError("expected string")
        return value

    @staticmethod
    def _boolean(value: Any) -> bool:
        if not isinstance(value, bool):
            raise ValueError("expected boolean")
        return value
