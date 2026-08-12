from __future__ import annotations

import asyncio
import unittest

from enterprise_rag.application.dto.model_catalog import (
    ModelCatalogEntryDto,
    ModelCatalogOrigin,
    ModelCompatibility,
)
from enterprise_rag.application.dto.model_download import (
    ModelDownloadProgressDto,
    ModelDownloadState,
)
from enterprise_rag.application.use_cases.model_download import (
    CancelModelDownload,
    DownloadModel,
)
from enterprise_rag.domain.errors import ApplicationError


def _entry(
    compatibility: ModelCompatibility = ModelCompatibility.SUPPORTED,
) -> ModelCatalogEntryDto:
    return ModelCatalogEntryDto(
        "mlx-community/Test-4bit",
        "a" * 40,
        ModelCatalogOrigin.HUGGING_FACE,
        False,
        1024,
        "4-bit",
        16_384,
        "apache-2.0",
        None,
        compatibility,
        "장비 검사 결과",
    )


class _Selection:
    def __init__(self, entry: ModelCatalogEntryDto) -> None:
        self.entry = entry
        self.arguments = None

    async def execute(self, *arguments):
        self.arguments = arguments
        return self.entry


class _Downloads:
    def __init__(self, entry: ModelCatalogEntryDto) -> None:
        self.entry = entry
        self.arguments = None
        self.cancelled = None

    async def download(self, *arguments):
        self.arguments = arguments
        return self.entry

    async def cancel(self, download_id: str) -> bool:
        self.cancelled = download_id
        return True


class ModelDownloadUseCaseTest(unittest.TestCase):
    def test_validates_selection_then_delegates_download_and_cancel(self) -> None:
        entry = _entry()
        selection = _Selection(entry)
        downloads = _Downloads(entry)

        def callback(_: object) -> None:
            return None

        download_id = "download-" + "1" * 32
        result = asyncio.run(
            DownloadModel(selection, downloads).execute(
                download_id,
                entry.model_id,
                entry.revision,
                callback,
            )
        )
        self.assertEqual(result, entry)
        self.assertEqual(
            selection.arguments,
            (entry.model_id, entry.revision, False),
        )
        self.assertEqual(
            downloads.arguments,
            (download_id, entry.model_id, entry.revision, callback),
        )
        self.assertTrue(asyncio.run(CancelModelDownload(downloads).execute(download_id)))
        self.assertEqual(downloads.cancelled, download_id)

    def test_rejects_bad_id_and_incompatible_model_before_download(self) -> None:
        for compatibility in (
            ModelCompatibility.UNSUPPORTED,
            ModelCompatibility.TOO_LARGE,
        ):
            entry = _entry(compatibility)
            downloads = _Downloads(entry)
            with self.subTest(compatibility=compatibility), self.assertRaises(
                ApplicationError
            ) as captured:
                asyncio.run(
                    DownloadModel(_Selection(entry), downloads).execute(
                        "download-" + "2" * 32,
                        entry.model_id,
                        entry.revision,
                        lambda _: None,
                    )
                )
            self.assertEqual(captured.exception.code, "MODEL_INCOMPATIBLE")
            self.assertIsNone(downloads.arguments)
        with self.assertRaises(ApplicationError):
            asyncio.run(
                CancelModelDownload(_Downloads(_entry())).execute("invalid")
            )
        gated_values = {
            field: getattr(_entry(), field)
            for field in _entry().__dataclass_fields__
        }
        gated = ModelCatalogEntryDto(**(gated_values | {"gated": True}))
        with self.assertRaises(ApplicationError) as captured:
            asyncio.run(
                DownloadModel(_Selection(gated), _Downloads(gated)).execute(
                    "download-" + "7" * 32,
                    gated.model_id,
                    gated.revision,
                    lambda _: None,
                )
            )
        self.assertEqual(captured.exception.code, "MODEL_ACCESS_DENIED")

    def test_progress_contract_calculates_bytes_or_files_and_rejects_invalid(self) -> None:
        values = {
            "download_id": "download-" + "3" * 32,
            "model_id": "mlx-community/Test-4bit",
            "revision": "a" * 40,
            "state": ModelDownloadState.DOWNLOADING,
            "completed_bytes": 25,
            "total_bytes": 100,
            "completed_files": 1,
            "total_files": 4,
            "message": "다운로드 중",
        }
        self.assertEqual(ModelDownloadProgressDto(**values).percentage, 25)
        file_values = values | {"completed_bytes": 0, "total_bytes": 0}
        self.assertEqual(ModelDownloadProgressDto(**file_values).percentage, 25)
        completed = file_values | {
            "completed_files": 0,
            "total_files": 0,
            "state": ModelDownloadState.COMPLETED,
        }
        self.assertEqual(ModelDownloadProgressDto(**completed).percentage, 100)
        invalid = (
            {"download_id": "bad"},
            {"model_id": "bad"},
            {"revision": "main"},
            {"completed_bytes": -1},
            {"completed_bytes": 101},
            {"completed_files": -1},
            {"completed_files": 5},
            {"message": ""},
        )
        for changes in invalid:
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                ModelDownloadProgressDto(**(values | changes))


if __name__ == "__main__":
    unittest.main()
