from __future__ import annotations

import asyncio
import unittest

from enterprise_rag.application.dto.model_catalog import (
    ModelCatalogDto,
    ModelCatalogEntryDto,
    ModelCatalogOrigin,
    ModelCompatibility,
)
from enterprise_rag.application.use_cases.model_catalog import (
    BrowseLocalModels,
    InspectModelSelection,
    SearchHuggingFaceModels,
)
from enterprise_rag.domain.errors import ApplicationError


def _entry(
    compatibility: ModelCompatibility = ModelCompatibility.SUPPORTED,
) -> ModelCatalogEntryDto:
    return ModelCatalogEntryDto(
        model_id="mlx-community/Test-4bit",
        revision="a" * 40,
        origin=ModelCatalogOrigin.LOCAL_CACHE,
        cached=True,
        size_bytes=8 * 1024**3,
        quantization="4-bit affine",
        context_tokens=16_384,
        license_name="apache-2.0",
        modified_at="2026-08-12T00:00:00Z",
        compatibility=compatibility,
        compatibility_detail="적합성 검사 결과",
        local_path="/cache/test",
    )


class _Catalog:
    def __init__(self, entry: ModelCatalogEntryDto) -> None:
        self.entry = entry
        self.arguments: tuple[object, ...] | None = None

    async def list_local(self, query: str, limit: int):
        self.arguments = (query, limit)
        return (self.entry,)

    async def search_remote(self, query: str, limit: int):
        self.arguments = (query, limit)
        return (self.entry,)

    async def inspect(self, model_id: str, revision: str, local_only: bool):
        self.arguments = (model_id, revision, local_only)
        return self.entry


class ModelCatalogUseCaseTest(unittest.TestCase):
    def test_browses_searches_and_inspects_normalized_model_catalog(self) -> None:
        catalog = _Catalog(_entry())
        local = asyncio.run(BrowseLocalModels(catalog).execute("  Test   4bit  ", 5))
        self.assertEqual(local.query, "Test 4bit")
        self.assertFalse(local.remote)
        remote = asyncio.run(SearchHuggingFaceModels(catalog).execute("", 10))
        self.assertTrue(remote.remote)
        inspected = asyncio.run(
            InspectModelSelection(catalog).execute(
                " mlx-community/Test-4bit ",
                "A" * 40,
                True,
            )
        )
        self.assertEqual(inspected.revision, "a" * 40)
        self.assertEqual(catalog.arguments, ("mlx-community/Test-4bit", "a" * 40, True))

    def test_rejects_invalid_requests_and_job_incompatible_model(self) -> None:
        catalog = _Catalog(_entry(ModelCompatibility.TOO_LARGE))
        for operation in (
            lambda: BrowseLocalModels(catalog).execute("x" * 201),
            lambda: BrowseLocalModels(catalog).execute("", 0),
            lambda: InspectModelSelection(catalog).execute("bad", "a" * 40, True),
        ):
            with self.subTest(operation=operation), self.assertRaises(ApplicationError):
                asyncio.run(operation())
        with self.assertRaises(ApplicationError) as captured:
            asyncio.run(
                InspectModelSelection(catalog).validate_for_job(
                    "mlx-community/Test-4bit",
                    "a" * 40,
                    False,
                )
            )
        self.assertEqual(captured.exception.code, "MODEL_INCOMPATIBLE")
        remote_values = {
            field: getattr(catalog.entry, field)
            for field in catalog.entry.__dataclass_fields__
        }
        remote_values.update(
            origin=ModelCatalogOrigin.HUGGING_FACE,
            cached=False,
            local_path=None,
            compatibility=ModelCompatibility.SUPPORTED,
        )
        remote_catalog = _Catalog(ModelCatalogEntryDto(**remote_values))
        with self.assertRaises(ApplicationError) as captured:
            asyncio.run(
                InspectModelSelection(remote_catalog).validate_for_job(
                    "mlx-community/Test-4bit",
                    "a" * 40,
                    False,
                )
            )
        self.assertEqual(captured.exception.code, "MODEL_NOT_CACHED")

    def test_rejects_inconsistent_or_duplicate_catalog_dto(self) -> None:
        valid = _entry()
        invalid_values = (
            {"model_id": "bad"},
            {"revision": "main"},
            {"size_bytes": -1},
            {"context_tokens": 0},
            {"quantization": ""},
            {"compatibility_detail": ""},
            {"cached": False},
        )
        baseline = {
            field: getattr(valid, field)
            for field in valid.__dataclass_fields__
        }
        for changes in invalid_values:
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                ModelCatalogEntryDto(**(baseline | changes))
        with self.assertRaises(ValueError):
            ModelCatalogDto("", False, (valid, valid))


if __name__ == "__main__":
    unittest.main()
