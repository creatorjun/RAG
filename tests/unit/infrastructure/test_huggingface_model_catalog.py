from __future__ import annotations

import asyncio
import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

from enterprise_rag.application.dto.model_catalog import (
    ModelCatalogOrigin,
    ModelCompatibility,
)
from enterprise_rag.domain.errors import ApplicationError
from enterprise_rag.infrastructure.models.huggingface_model_catalog import (
    HuggingFaceModelCatalog,
)

_GIB = 1024**3


class _RepositoryNotFoundError(Exception):
    pass


class _RevisionNotFoundError(Exception):
    pass


class _GatedRepoError(_RepositoryNotFoundError):
    pass


class _Api:
    def __init__(self, models=(), info=None, error=None) -> None:
        self.models = models
        self.info = info
        self.error = error
        self.list_options = None
        self.info_options = None

    def list_models(self, **options):
        self.list_options = options
        if self.error is not None:
            raise self.error
        return self.models

    def model_info(self, model_id, **options):
        self.info_options = (model_id, options)
        if self.error is not None:
            raise self.error
        return self.info


def _module(cache, api: _Api):
    return SimpleNamespace(
        scan_cache_dir=lambda: cache,
        HfApi=lambda: api,
        errors=SimpleNamespace(
            RepositoryNotFoundError=_RepositoryNotFoundError,
            RevisionNotFoundError=_RevisionNotFoundError,
            GatedRepoError=_GatedRepoError,
        ),
    )


class HuggingFaceModelCatalogTest(unittest.TestCase):
    def _cache(self, snapshot: Path):
        revision = SimpleNamespace(
            commit_hash="a" * 40,
            size_on_disk=16 * _GIB,
            last_modified=1_786_492_218.0,
            snapshot_path=snapshot,
        )
        repository = SimpleNamespace(
            repo_id="mlx-community/Local-4bit",
            repo_type="model",
            revisions=(revision,),
        )
        return SimpleNamespace(repos=(repository,))

    def test_lists_local_snapshot_metadata_and_hardware_fit(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            snapshot = Path(temporary).resolve()
            (snapshot / "config.json").write_text(
                json.dumps(
                    {
                        "quantization": {"bits": 4, "mode": "affine"},
                        "text_config": {"max_position_embeddings": 262_144},
                    }
                ),
                encoding="utf-8",
            )
            api = _Api()
            catalog = HuggingFaceModelCatalog(
                module_loader=lambda: _module(self._cache(snapshot), api),
                system_name="Darwin",
                machine_name="arm64",
                physical_memory_bytes=36 * _GIB,
            )
            entries = asyncio.run(catalog.list_local("local", 10))
            self.assertEqual(len(entries), 1)
            entry = entries[0]
            self.assertEqual(entry.origin, ModelCatalogOrigin.LOCAL_CACHE)
            self.assertEqual(entry.quantization, "4-bit affine")
            self.assertEqual(entry.context_tokens, 262_144)
            self.assertEqual(entry.compatibility, ModelCompatibility.SUPPORTED)
            self.assertTrue(entry.cached)
            self.assertEqual(
                asyncio.run(catalog.inspect(entry.model_id, entry.revision, True)),
                entry,
            )

    def test_searches_latest_remote_mlx_models_and_preserves_exact_commit(self) -> None:
        cache = SimpleNamespace(repos=())
        remote = SimpleNamespace(
            id="mlx-community/Remote-8bit",
            sha="b" * 40,
            config={"max_position_embeddings": 32_768},
            used_storage=8 * _GIB,
            siblings=(),
            card_data=SimpleNamespace(license="apache-2.0"),
            last_modified=datetime(2026, 8, 12, tzinfo=timezone.utc),
            gated=False,
        )
        invalid = SimpleNamespace(id="mlx-community/Invalid", sha="main")
        api = _Api(models=(remote, invalid), info=remote)
        catalog = HuggingFaceModelCatalog(
            module_loader=lambda: _module(cache, api),
            system_name="Darwin",
            machine_name="arm64",
            physical_memory_bytes=36 * _GIB,
        )
        entries = asyncio.run(catalog.search_remote("Remote", 25))
        self.assertEqual(len(entries), 1)
        self.assertFalse(entries[0].cached)
        self.assertEqual(entries[0].revision, "b" * 40)
        self.assertEqual(entries[0].license_name, "apache-2.0")
        self.assertEqual(api.list_options["author"], "mlx-community")
        inspected = asyncio.run(
            catalog.inspect("mlx-community/Remote-8bit", "b" * 40, False)
        )
        self.assertEqual(inspected.revision, "b" * 40)
        self.assertTrue(api.info_options[1]["files_metadata"])

    def test_reports_cache_miss_platform_memory_and_remote_errors(self) -> None:
        cache = SimpleNamespace(repos=())
        api = _Api()
        catalog = HuggingFaceModelCatalog(
            module_loader=lambda: _module(cache, api),
            system_name="Linux",
            machine_name="x86_64",
            physical_memory_bytes=16 * _GIB,
        )
        with self.assertRaises(ApplicationError) as captured:
            asyncio.run(catalog.inspect("mlx-community/Missing", "c" * 40, True))
        self.assertEqual(captured.exception.code, "MODEL_NOT_CACHED")

        remote = SimpleNamespace(
            id="mlx-community/Huge-4bit",
            sha="d" * 40,
            config={},
            used_storage=20 * _GIB,
            siblings=(),
            card_data=None,
            last_modified=None,
            gated="manual",
        )
        api.models = (remote,)
        entries = asyncio.run(catalog.search_remote("Huge", 5))
        self.assertEqual(entries[0].compatibility, ModelCompatibility.UNSUPPORTED)
        self.assertTrue(entries[0].gated)

        for error, code in (
            (_RepositoryNotFoundError(), "MODEL_SELECTION_INVALID"),
            (_GatedRepoError(), "MODEL_ACCESS_DENIED"),
            (OSError("offline"), "MODEL_CATALOG_UNAVAILABLE"),
        ):
            failed = _Api(error=error)
            failing_catalog = HuggingFaceModelCatalog(
                module_loader=lambda failed=failed: _module(cache, failed),
                system_name="Darwin",
                machine_name="arm64",
                physical_memory_bytes=36 * _GIB,
            )
            with self.subTest(code=code), self.assertRaises(ApplicationError) as captured:
                asyncio.run(failing_catalog.search_remote("test", 5))
            self.assertEqual(captured.exception.code, code)


if __name__ == "__main__":
    unittest.main()
