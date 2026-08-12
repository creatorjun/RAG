from __future__ import annotations

import asyncio
import importlib
import json
import shutil
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from enterprise_rag.application.dto.model_catalog import ModelCatalogEntryDto
from enterprise_rag.application.dto.model_download import (
    ModelDownloadProgressDto,
    ModelDownloadState,
)
from enterprise_rag.application.ports.model_catalog import ModelCatalogPort
from enterprise_rag.application.ports.model_download import (
    ModelDownloadProgressCallback,
)
from enterprise_rag.domain.errors import ApplicationError, revision_error


@dataclass(slots=True)
class _DownloadSession:
    cancelled: threading.Event
    tracker: _ProgressTracker | None = None


class _ProgressTracker:
    def __init__(
        self,
        download_id: str,
        model_id: str,
        revision: str,
        total_bytes: int,
        total_files: int,
        callback: ModelDownloadProgressCallback,
        cancelled: threading.Event,
    ) -> None:
        self.download_id = download_id
        self.model_id = model_id
        self.revision = revision
        self.total_bytes = total_bytes
        self.total_files = total_files
        self.completed_bytes = 0
        self.completed_files = 0
        self._callback = callback
        self._cancelled = cancelled
        self._lock = threading.Lock()
        self._last_emit = 0.0
        self._last_percentage = -1

    def check_cancelled(self) -> None:
        if self._cancelled.is_set():
            raise revision_error(
                "MODEL_DOWNLOAD_CANCELLED", {"download_id": self.download_id}
            )

    def add_bytes(self, value: int | float | None) -> None:
        self.check_cancelled()
        amount = max(0, int(value or 0))
        with self._lock:
            self.completed_bytes = min(
                self.total_bytes,
                self.completed_bytes + amount,
            )
        self.emit(ModelDownloadState.DOWNLOADING, "모델 데이터를 다운로드하는 중입니다.")

    def add_file(self) -> None:
        self.check_cancelled()
        with self._lock:
            self.completed_files = min(self.total_files, self.completed_files + 1)
        self.emit(ModelDownloadState.DOWNLOADING, "모델 파일을 저장하는 중입니다.")

    def complete_transfer(self) -> None:
        with self._lock:
            self.completed_bytes = self.total_bytes
            self.completed_files = self.total_files
        self.emit(
            ModelDownloadState.DOWNLOADING,
            "모든 모델 파일을 받았습니다.",
            force=True,
        )

    def emit(
        self,
        state: ModelDownloadState,
        message: str,
        force: bool = False,
    ) -> None:
        with self._lock:
            progress = ModelDownloadProgressDto(
                self.download_id,
                self.model_id,
                self.revision,
                state,
                self.completed_bytes,
                self.total_bytes,
                self.completed_files,
                self.total_files,
                message,
            )
            now = time.monotonic()
            if (
                not force
                and progress.percentage == self._last_percentage
                and now - self._last_emit < 0.1
            ):
                return
            self._last_emit = now
            self._last_percentage = progress.percentage
        self._callback(progress)

    def tqdm_class(self, base: type[Any]) -> type[Any]:
        tracker = self

        class DownloadProgressTqdm(base):  # type: ignore[misc]
            def __init__(self, *args: Any, **kwargs: Any) -> None:
                description = str(kwargs.get("desc", ""))
                self._track_bytes = description == "Downloading bytes"
                self._track_files = description.startswith("Fetching ")
                kwargs["disable"] = True
                tracker.check_cancelled()
                super().__init__(*args, **kwargs)

            def update(self, n: int | float | None = 1) -> Any:
                if self._track_bytes:
                    tracker.add_bytes(n)
                else:
                    tracker.check_cancelled()
                return super().update(n)

            def __iter__(self) -> Any:
                for value in super().__iter__():
                    tracker.check_cancelled()
                    yield value
                    if self._track_files:
                        tracker.add_file()

        return DownloadProgressTqdm


class HuggingFaceModelDownloader:
    def __init__(
        self,
        catalog: ModelCatalogPort,
        reserve_bytes: int,
        cache_root: Path | None = None,
        module_loader: Any | None = None,
        disk_usage: Any | None = None,
    ) -> None:
        if reserve_bytes < 0:
            raise ValueError("download disk reserve must be non-negative")
        self._catalog = catalog
        self._reserve_bytes = reserve_bytes
        self._cache_root_override = cache_root
        self._module_loader = module_loader or self._load_module
        self._disk_usage = disk_usage or shutil.disk_usage
        self._sessions: dict[str, _DownloadSession] = {}
        self._sessions_lock = threading.Lock()

    async def download(
        self,
        download_id: str,
        model_id: str,
        revision: str,
        progress: ModelDownloadProgressCallback,
    ) -> ModelCatalogEntryDto:
        session = _DownloadSession(threading.Event())
        with self._sessions_lock:
            if self._sessions:
                raise revision_error(
                    "MODEL_DOWNLOAD_CONFLICT", {"download_id": download_id}
                )
            self._sessions[download_id] = session
        try:
            snapshot = await asyncio.to_thread(
                self._download_sync,
                session,
                download_id,
                model_id,
                revision,
                progress,
            )
            tracker = session.tracker
            if tracker is None:
                raise revision_error("MODEL_SNAPSHOT_INVALID", {"model_id": model_id})
            tracker.check_cancelled()
            tracker.emit(
                ModelDownloadState.VERIFYING,
                "다운로드된 snapshot과 가중치 파일을 검증하는 중입니다.",
                force=True,
            )
            await asyncio.to_thread(self._validate_snapshot, snapshot, revision)
            tracker.check_cancelled()
            try:
                entry = await self._catalog.inspect(model_id, revision, True)
            except ApplicationError as error:
                if error.code in {"MODEL_NOT_CACHED", "MODEL_SELECTION_INVALID"}:
                    raise revision_error(
                        "MODEL_SNAPSHOT_INVALID", {"model_id": model_id}
                    ) from error
                raise
            if entry.local_path is None or Path(entry.local_path).resolve(
                strict=True
            ) != snapshot:
                raise revision_error("MODEL_SNAPSHOT_INVALID", {"model_id": model_id})
            tracker.emit(
                ModelDownloadState.COMPLETED,
                "모델 다운로드와 snapshot 검증이 완료되었습니다.",
                force=True,
            )
            return entry
        except ApplicationError as error:
            if error.code == "MODEL_DOWNLOAD_CANCELLED":
                self._emit_cancelled(
                    session,
                    download_id,
                    model_id,
                    revision,
                    progress,
                )
            raise
        except Exception as error:
            raise revision_error(
                "MODEL_DOWNLOAD_FAILED",
                {"download_id": download_id, "model_id": model_id},
            ) from error
        finally:
            with self._sessions_lock:
                self._sessions.pop(download_id, None)

    async def cancel(self, download_id: str) -> bool:
        with self._sessions_lock:
            session = self._sessions.get(download_id)
            if session is None:
                return False
            session.cancelled.set()
            return True

    def _download_sync(
        self,
        session: _DownloadSession,
        download_id: str,
        model_id: str,
        revision: str,
        progress: ModelDownloadProgressCallback,
    ) -> Path:
        module = self._module()
        cache_root = self._cache_root(module)
        session.cancelled.is_set() and self._raise_cancelled(download_id)
        progress(
            ModelDownloadProgressDto(
                download_id,
                model_id,
                revision,
                ModelDownloadState.PREFLIGHT,
                0,
                0,
                0,
                0,
                "파일 목록과 필요한 디스크 용량을 계산하는 중입니다.",
            )
        )
        try:
            dry_run = module.snapshot_download(
                repo_id=model_id,
                revision=revision,
                cache_dir=str(cache_root),
                local_files_only=False,
                dry_run=True,
            )
        except ApplicationError:
            raise
        except Exception as error:
            raise revision_error(
                "MODEL_DOWNLOAD_FAILED", {"model_id": model_id}
            ) from error
        if not isinstance(dry_run, list) or not dry_run:
            raise revision_error("MODEL_SNAPSHOT_INVALID", {"model_id": model_id})
        commit_hashes = {str(value.commit_hash).lower() for value in dry_run}
        if commit_hashes != {revision}:
            raise revision_error("MODEL_SNAPSHOT_INVALID", {"model_id": model_id})
        total_bytes = sum(
            max(0, int(value.file_size))
            for value in dry_run
            if bool(value.will_download)
        )
        tracker = _ProgressTracker(
            download_id,
            model_id,
            revision,
            total_bytes,
            len(dry_run),
            progress,
            session.cancelled,
        )
        session.tracker = tracker
        tracker.check_cancelled()
        free_bytes = int(self._disk_usage(cache_root).free)
        required_bytes = total_bytes + self._reserve_bytes
        if free_bytes < required_bytes:
            raise revision_error(
                "MODEL_DOWNLOAD_DISK_SPACE",
                {
                    "required_bytes": required_bytes,
                    "free_bytes": free_bytes,
                },
            )
        tracker.emit(
            ModelDownloadState.DOWNLOADING,
            "디스크 검사를 통과해 모델 다운로드를 시작합니다.",
            force=True,
        )
        try:
            result = module.snapshot_download(
                repo_id=model_id,
                revision=revision,
                cache_dir=str(cache_root),
                local_files_only=False,
                dry_run=False,
                tqdm_class=tracker.tqdm_class(module.utils.tqdm),
            )
        except ApplicationError:
            raise
        except Exception as error:
            if session.cancelled.is_set():
                self._raise_cancelled(download_id)
            raise revision_error(
                "MODEL_DOWNLOAD_FAILED", {"model_id": model_id}
            ) from error
        tracker.check_cancelled()
        tracker.complete_transfer()
        try:
            return Path(result).expanduser().resolve(strict=True)
        except (OSError, TypeError) as error:
            raise revision_error(
                "MODEL_SNAPSHOT_INVALID", {"model_id": model_id}
            ) from error

    @staticmethod
    def _validate_snapshot(snapshot: Path, revision: str) -> None:
        try:
            if not snapshot.is_dir() or snapshot.name != revision:
                raise ValueError("snapshot identity is invalid")
            config = json.loads((snapshot / "config.json").read_text(encoding="utf-8"))
            if not isinstance(config, dict) or not config:
                raise ValueError("model config is invalid")
            weights = tuple(snapshot.rglob("*.safetensors")) + tuple(
                snapshot.rglob("*.npz")
            )
            if not weights or any(not path.is_file() for path in weights):
                raise ValueError("model weights are missing")
        except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError) as error:
            raise revision_error("MODEL_SNAPSHOT_INVALID") from error

    def _cache_root(self, module: Any) -> Path:
        value = self._cache_root_override
        if value is None:
            value = Path(str(module.constants.HF_HUB_CACHE))
        try:
            value.expanduser().mkdir(parents=True, exist_ok=True)
            return value.expanduser().resolve(strict=True)
        except OSError as error:
            raise revision_error("IO_FAILURE") from error

    @staticmethod
    def _emit_cancelled(
        session: _DownloadSession,
        download_id: str,
        model_id: str,
        revision: str,
        progress: ModelDownloadProgressCallback,
    ) -> None:
        tracker = session.tracker
        if tracker is not None:
            tracker.emit(
                ModelDownloadState.CANCELLED,
                "모델 다운로드가 취소되었습니다. 불완전 파일은 사용하지 않습니다.",
                force=True,
            )
            return
        progress(
            ModelDownloadProgressDto(
                download_id,
                model_id,
                revision,
                ModelDownloadState.CANCELLED,
                0,
                0,
                0,
                0,
                "모델 다운로드가 취소되었습니다.",
            )
        )

    @staticmethod
    def _raise_cancelled(download_id: str) -> None:
        raise revision_error(
            "MODEL_DOWNLOAD_CANCELLED", {"download_id": download_id}
        )

    def _module(self) -> Any:
        try:
            return self._module_loader()
        except ModuleNotFoundError as error:
            raise revision_error(
                "DEPENDENCY_MISSING", {"dependency": "huggingface-hub"}
            ) from error

    @staticmethod
    def _load_module() -> Any:
        return importlib.import_module("huggingface_hub")
