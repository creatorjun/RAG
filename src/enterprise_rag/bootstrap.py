# src/enterprise_rag/bootstrap.py
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from enterprise_rag.application.use_cases.compare_revision_run import CompareRevisionRun
from enterprise_rag.application.use_cases.finalize_revision_run import FinalizeRevisionRun
from enterprise_rag.application.use_cases.prepare_revision_run import PrepareRevisionRun
from enterprise_rag.infrastructure.clock.system import SystemClock, UuidIdGenerator
from enterprise_rag.infrastructure.config.settings import LoadedSettings, SettingsLoader
from enterprise_rag.infrastructure.workspace.folder_revision_workspace import (
    FolderRevisionWorkspace,
)
from enterprise_rag.infrastructure.workspace.folder_tree_comparator import FolderTreeComparator


@dataclass(frozen=True, slots=True)
class Application:
    configuration: LoadedSettings
    prepare_revision_run: PrepareRevisionRun
    compare_revision_run: CompareRevisionRun
    finalize_revision_run: FinalizeRevisionRun

    def close(self) -> None:
        return None

    def __enter__(self) -> Application:
        return self

    def __exit__(self, exception_type: object, exception: object, traceback: object) -> None:
        self.close()


def build_application(project_root: Path, environment: str | None = None) -> Application:
    configuration = SettingsLoader(project_root).load(environment)
    workspace = FolderRevisionWorkspace(
        before_root=configuration.paths.before_root,
        after_root=configuration.paths.after_root,
        comparator=FolderTreeComparator(),
        clock=SystemClock(),
        id_generator=UuidIdGenerator(),
        max_file_bytes=configuration.settings.sources.max_file_bytes,
    )
    return Application(
        configuration=configuration,
        prepare_revision_run=PrepareRevisionRun(workspace),
        compare_revision_run=CompareRevisionRun(workspace),
        finalize_revision_run=FinalizeRevisionRun(workspace),
    )
