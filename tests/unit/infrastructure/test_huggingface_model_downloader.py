from __future__ import annotations

import asyncio
import json
import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace

from tqdm.auto import tqdm

from enterprise_rag.application.dto.model_catalog import (
    ModelCatalogEntryDto,
    ModelCatalogOrigin,
    ModelCompatibility,
)
from enterprise_rag.application.dto.model_download import ModelDownloadState
from enterprise_rag.domain.errors import ApplicationError
from enterprise_rag.infrastructure.models.huggingface_model_downloader import (
    HuggingFaceModelDownloader,
)


class _Catalog:
    def __init__(self, snapshot: Path) -> None:
        self.snapshot = snapshot

    async def inspect(self, model_id: str, revision: str, local_only: bool):
        return ModelCatalogEntryDto(
            model_id,
            revision,
            ModelCatalogOrigin.LOCAL_CACHE,
            True,
            100,
            "4-bit",
            16_384,
            "apache-2.0",
            None,
            ModelCompatibility.SUPPORTED,
            "적합",
            str(self.snapshot),
        )


class _Hub:
    def __init__(
        self,
        cache_root: Path,
        revision: str,
        valid_snapshot: bool = True,
    ) -> None:
        self.constants = SimpleNamespace(HF_HUB_CACHE=str(cache_root))
        self.utils = SimpleNamespace(tqdm=tqdm)
        self.revision = revision
        self.snapshot = cache_root / "models--test" / "snapshots" / revision
        self.valid_snapshot = valid_snapshot
        self.actual_started = threading.Event()
        self.release_actual: threading.Event | None = None
        self.calls: list[dict[str, object]] = []

    def snapshot_download(self, **options):
        self.calls.append(options)
        if options["dry_run"]:
            return [
                SimpleNamespace(
                    commit_hash=self.revision,
                    file_size=60,
                    filename="config.json",
                    will_download=True,
                ),
                SimpleNamespace(
                    commit_hash=self.revision,
                    file_size=40,
                    filename="model.safetensors",
                    will_download=True,
                ),
            ]
        self.actual_started.set()
        if self.release_actual is not None:
            self.release_actual.wait(timeout=2)
        progress_type = options["tqdm_class"]
        transfer = progress_type(total=100, desc="Downloading bytes")
        transfer.update(60)
        transfer.update(40)
        files = progress_type(range(2), total=2, desc="Fetching 2 files")
        list(files)
        self.snapshot.mkdir(parents=True, exist_ok=True)
        (self.snapshot / "config.json").write_text(
            json.dumps({"model_type": "test"}),
            encoding="utf-8",
        )
        if self.valid_snapshot:
            (self.snapshot / "model.safetensors").write_bytes(b"weights")
        return str(self.snapshot)


class HuggingFaceModelDownloaderTest(unittest.TestCase):
    def _downloader(
        self,
        root: Path,
        hub: _Hub,
        free_bytes: int = 10_000,
        reserve_bytes: int = 100,
    ) -> HuggingFaceModelDownloader:
        return HuggingFaceModelDownloader(
            _Catalog(hub.snapshot),
            reserve_bytes,
            cache_root=root,
            module_loader=lambda: hub,
            disk_usage=lambda _: SimpleNamespace(free=free_bytes),
        )

    def test_preflights_tracks_files_and_bytes_then_revalidates_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            revision = "a" * 40
            hub = _Hub(root, revision)
            downloader = self._downloader(root, hub)
            progress = []
            result = asyncio.run(
                downloader.download(
                    "download-" + "1" * 32,
                    "mlx-community/Test-4bit",
                    revision,
                    progress.append,
                )
            )
            self.assertTrue(result.cached)
            self.assertEqual(
                [
                    item.state
                    for item in progress
                    if item.state is not ModelDownloadState.DOWNLOADING
                ],
                [
                    ModelDownloadState.PREFLIGHT,
                    ModelDownloadState.VERIFYING,
                    ModelDownloadState.COMPLETED,
                ],
            )
            self.assertEqual(progress[-1].percentage, 100)
            self.assertEqual(progress[-1].completed_files, 2)
            self.assertEqual(hub.calls[0]["dry_run"], True)
            self.assertEqual(hub.calls[1]["dry_run"], False)

    def test_rejects_insufficient_disk_and_invalid_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            revision = "b" * 40
            hub = _Hub(root, revision)
            with self.assertRaises(ApplicationError) as captured:
                asyncio.run(
                    self._downloader(root, hub, free_bytes=199).download(
                        "download-" + "2" * 32,
                        "mlx-community/Test-4bit",
                        revision,
                        lambda _: None,
                    )
                )
            self.assertEqual(captured.exception.code, "MODEL_DOWNLOAD_DISK_SPACE")
            self.assertEqual(len(hub.calls), 1)

            invalid = _Hub(root, "c" * 40, valid_snapshot=False)
            with self.assertRaises(ApplicationError) as captured:
                asyncio.run(
                    self._downloader(root, invalid).download(
                        "download-" + "3" * 32,
                        "mlx-community/Test-4bit",
                        "c" * 40,
                        lambda _: None,
                    )
                )
            self.assertEqual(captured.exception.code, "MODEL_SNAPSHOT_INVALID")

    def test_cancels_safely_and_rejects_concurrent_download(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            revision = "d" * 40
            hub = _Hub(root, revision)
            downloader = self._downloader(root, hub)
            states = []
            download_id = "download-" + "4" * 32

            def cancel_at_preflight(value):
                states.append(value.state)
                if value.state is ModelDownloadState.PREFLIGHT:
                    asyncio.run(downloader.cancel(download_id))

            with self.assertRaises(ApplicationError) as captured:
                asyncio.run(
                    downloader.download(
                        download_id,
                        "mlx-community/Test-4bit",
                        revision,
                        cancel_at_preflight,
                    )
                )
            self.assertEqual(captured.exception.code, "MODEL_DOWNLOAD_CANCELLED")
            self.assertEqual(states[-1], ModelDownloadState.CANCELLED)
            self.assertFalse(asyncio.run(downloader.cancel(download_id)))

            blocking_hub = _Hub(root, "e" * 40)
            blocking_hub.release_actual = threading.Event()
            blocking = self._downloader(root, blocking_hub)

            async def concurrent() -> None:
                first = asyncio.create_task(
                    blocking.download(
                        "download-" + "5" * 32,
                        "mlx-community/Test-4bit",
                        "e" * 40,
                        lambda _: None,
                    )
                )
                await asyncio.to_thread(blocking_hub.actual_started.wait, 1)
                with self.assertRaises(ApplicationError) as conflict:
                    await blocking.download(
                        "download-" + "6" * 32,
                        "mlx-community/Other-4bit",
                        "f" * 40,
                        lambda _: None,
                    )
                self.assertEqual(conflict.exception.code, "MODEL_DOWNLOAD_CONFLICT")
                blocking_hub.release_actual.set()
                await first

            asyncio.run(concurrent())


if __name__ == "__main__":
    unittest.main()
