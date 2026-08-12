from __future__ import annotations

import asyncio
import importlib
import json
import os
import platform
import re
from collections.abc import Callable, Iterable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from enterprise_rag.application.dto.model_catalog import (
    ModelCatalogEntryDto,
    ModelCatalogOrigin,
    ModelCompatibility,
)
from enterprise_rag.domain.errors import (
    ApplicationError,
    ErrorCategory,
    revision_error,
)

_GIB = 1024**3


class HuggingFaceModelCatalog:
    def __init__(
        self,
        module_loader: Callable[[], Any] | None = None,
        system_name: str | None = None,
        machine_name: str | None = None,
        physical_memory_bytes: int | None = None,
    ) -> None:
        self._module_loader = module_loader or self._load_module
        self._system_name = system_name or platform.system()
        self._machine_name = machine_name or platform.machine()
        self._memory_bytes = physical_memory_bytes or self._physical_memory()

    async def list_local(
        self,
        query: str,
        limit: int,
    ) -> tuple[ModelCatalogEntryDto, ...]:
        return await asyncio.to_thread(self._list_local, query, limit)

    async def search_remote(
        self,
        query: str,
        limit: int,
    ) -> tuple[ModelCatalogEntryDto, ...]:
        return await asyncio.to_thread(self._search_remote, query, limit)

    async def inspect(
        self,
        model_id: str,
        revision: str,
        local_only: bool,
    ) -> ModelCatalogEntryDto:
        return await asyncio.to_thread(
            self._inspect,
            model_id,
            revision,
            local_only,
        )

    def _list_local(
        self,
        query: str,
        limit: int,
    ) -> tuple[ModelCatalogEntryDto, ...]:
        entries = self._local_entries()
        lowered = query.casefold()
        if lowered:
            entries = tuple(
                entry for entry in entries if lowered in entry.model_id.casefold()
            )
        return entries[:limit]

    def _search_remote(
        self,
        query: str,
        limit: int,
    ) -> tuple[ModelCatalogEntryDto, ...]:
        module = self._module()
        local = {
            (entry.model_id, entry.revision): entry for entry in self._local_entries()
        }
        try:
            values = module.HfApi().list_models(
                author="mlx-community",
                search=query,
                sort="last_modified",
                limit=limit,
                expand=[
                    "cardData",
                    "config",
                    "gated",
                    "lastModified",
                    "library_name",
                    "pipeline_tag",
                    "sha",
                    "siblings",
                    "tags",
                    "usedStorage",
                ],
            )
            entries: list[ModelCatalogEntryDto] = []
            for value in values:
                entry = self._remote_entry(value, local)
                if entry is not None:
                    entries.append(entry)
            return tuple(entries)
        except ApplicationError:
            raise
        except Exception as error:
            raise self._remote_error(error, query=query) from error

    def _inspect(
        self,
        model_id: str,
        revision: str,
        local_only: bool,
    ) -> ModelCatalogEntryDto:
        local = {
            (entry.model_id, entry.revision): entry for entry in self._local_entries()
        }
        cached = local.get((model_id, revision))
        if cached is not None:
            return cached
        if local_only:
            raise revision_error(
                "MODEL_NOT_CACHED",
                {"model_id": model_id, "model_revision": revision},
            )
        module = self._module()
        try:
            value = module.HfApi().model_info(
                model_id,
                revision=revision,
                files_metadata=True,
            )
            entry = self._remote_entry(value, local)
            if entry is None or entry.revision != revision:
                raise revision_error(
                    "MODEL_SELECTION_INVALID",
                    {"model_id": model_id, "model_revision": revision},
                )
            return entry
        except ApplicationError:
            raise
        except Exception as error:
            raise self._remote_error(error, model_id=model_id) from error

    def _local_entries(self) -> tuple[ModelCatalogEntryDto, ...]:
        module = self._module()
        try:
            cache = module.scan_cache_dir()
            values: list[tuple[float, ModelCatalogEntryDto]] = []
            for repository in cache.repos:
                if getattr(repository, "repo_type", None) != "model":
                    continue
                for revision in repository.revisions:
                    modified = float(getattr(revision, "last_modified", 0.0) or 0.0)
                    values.append(
                        (modified, self._local_entry(repository, revision, modified))
                    )
            values.sort(key=lambda item: (-item[0], item[1].model_id))
            return tuple(entry for _, entry in values)
        except ApplicationError:
            raise
        except Exception as error:
            raise revision_error("MODEL_SELECTION_INVALID") from error

    def _local_entry(
        self,
        repository: Any,
        revision: Any,
        modified: float,
    ) -> ModelCatalogEntryDto:
        snapshot = Path(revision.snapshot_path).expanduser().resolve(strict=True)
        config = self._read_config(snapshot)
        model_id = str(repository.repo_id)
        size = self._positive_integer(getattr(revision, "size_on_disk", None))
        compatibility, detail = self._compatibility(model_id, size)
        return ModelCatalogEntryDto(
            model_id=model_id,
            revision=str(revision.commit_hash).lower(),
            origin=ModelCatalogOrigin.LOCAL_CACHE,
            cached=True,
            size_bytes=size,
            quantization=self._quantization(config, model_id),
            context_tokens=self._context_tokens(config),
            license_name="확인 필요",
            modified_at=self._timestamp(modified),
            compatibility=compatibility,
            compatibility_detail=detail,
            local_path=str(snapshot),
        )

    def _remote_entry(
        self,
        value: Any,
        local: dict[tuple[str, str], ModelCatalogEntryDto],
    ) -> ModelCatalogEntryDto | None:
        model_id = str(getattr(value, "id", ""))
        revision = str(getattr(value, "sha", "")).lower()
        if re.fullmatch(r"[0-9a-f]{40}", revision) is None:
            return None
        cached = local.get((model_id, revision))
        if cached is not None:
            return cached
        config = getattr(value, "config", None)
        if not isinstance(config, dict):
            config = {}
        size = self._remote_size(value)
        compatibility, detail = self._compatibility(model_id, size)
        return ModelCatalogEntryDto(
            model_id=model_id,
            revision=revision,
            origin=ModelCatalogOrigin.HUGGING_FACE,
            cached=False,
            size_bytes=size,
            quantization=self._quantization(config, model_id),
            context_tokens=self._context_tokens(config),
            license_name=self._license(value),
            modified_at=self._timestamp(getattr(value, "last_modified", None)),
            compatibility=compatibility,
            compatibility_detail=detail,
            local_path=None,
            gated=bool(getattr(value, "gated", False)),
        )

    def _compatibility(
        self,
        model_id: str,
        size_bytes: int | None,
    ) -> tuple[ModelCompatibility, str]:
        if self._system_name != "Darwin" or self._machine_name != "arm64":
            return (
                ModelCompatibility.UNSUPPORTED,
                "MLX 생성 모델은 Apple Silicon macOS에서만 지원됩니다.",
            )
        lowered = model_id.casefold()
        if not (lowered.startswith("mlx-community/") or "mlx" in lowered):
            return (
                ModelCompatibility.UNSUPPORTED,
                "MLX 변환 모델로 확인되지 않았습니다.",
            )
        if size_bytes is None or self._memory_bytes is None:
            return (
                ModelCompatibility.UNKNOWN,
                "모델 크기 또는 물리 메모리를 확인할 수 없습니다.",
            )
        estimated = int(size_bytes * 1.2) + 4 * _GIB
        ratio = estimated / self._memory_bytes
        required = estimated / _GIB
        total = self._memory_bytes / _GIB
        if ratio <= 0.70:
            return (
                ModelCompatibility.SUPPORTED,
                f"예상 필요 {required:.1f} GiB / 물리 메모리 {total:.1f} GiB",
            )
        if ratio <= 0.85:
            return (
                ModelCompatibility.TIGHT,
                f"메모리 여유가 작습니다: 예상 {required:.1f} / 전체 {total:.1f} GiB",
            )
        return (
            ModelCompatibility.TOO_LARGE,
            f"안전 한도 초과: 예상 {required:.1f} / 전체 {total:.1f} GiB",
        )

    @staticmethod
    def _read_config(snapshot: Path) -> dict[str, Any]:
        path = snapshot / "config.json"
        if not path.is_file():
            return {}
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            return {}
        return value if isinstance(value, dict) else {}

    @staticmethod
    def _quantization(config: dict[str, Any], model_id: str) -> str:
        value = config.get("quantization") or config.get("quantization_config")
        if isinstance(value, dict):
            bits = value.get("bits")
            mode = value.get("mode") or value.get("quant_method")
            if isinstance(bits, int) and not isinstance(bits, bool):
                suffix = "" if not isinstance(mode, str) else f" {mode}"
                return f"{bits}-bit{suffix}"
        lowered = model_id.casefold()
        match = re.search(r"(?:^|[-_])(\d+)[-_]?bit(?:$|[-_])", lowered)
        return "확인 필요" if match is None else f"{match.group(1)}-bit"

    @classmethod
    def _context_tokens(cls, config: dict[str, Any]) -> int | None:
        candidates: Iterable[Any] = (
            config.get("max_position_embeddings"),
            config.get("model_max_length"),
        )
        text_config = config.get("text_config")
        if isinstance(text_config, dict):
            candidates = (
                *candidates,
                text_config.get("max_position_embeddings"),
                text_config.get("model_max_length"),
            )
        for value in candidates:
            parsed = cls._positive_integer(value)
            if parsed is not None:
                return parsed
        return None

    @classmethod
    def _remote_size(cls, value: Any) -> int | None:
        direct = cls._positive_integer(getattr(value, "used_storage", None))
        if direct is not None:
            return direct
        total = 0
        found = False
        for sibling in getattr(value, "siblings", None) or ():
            size = cls._positive_integer(getattr(sibling, "size", None))
            if size is not None:
                total += size
                found = True
        return total if found else None

    @staticmethod
    def _license(value: Any) -> str:
        card = getattr(value, "card_data", None)
        license_name = getattr(card, "license", None)
        if license_name is None and isinstance(card, dict):
            license_name = card.get("license")
        if isinstance(license_name, list):
            return ", ".join(str(item) for item in license_name) or "확인 필요"
        return license_name if isinstance(license_name, str) else "확인 필요"

    @staticmethod
    def _timestamp(value: Any) -> str | None:
        if value is None:
            return None
        if isinstance(value, datetime):
            moment = value if value.utcoffset() is not None else value.replace(tzinfo=timezone.utc)
        else:
            try:
                moment = datetime.fromtimestamp(float(value), tz=timezone.utc)
            except (TypeError, ValueError, OSError):
                return None
        return moment.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")

    @staticmethod
    def _positive_integer(value: Any) -> int | None:
        if isinstance(value, bool) or not isinstance(value, (int, float)) or value <= 0:
            return None
        return int(value)

    def _remote_error(self, error: Exception, **context: str) -> ApplicationError:
        module = self._module()
        errors = getattr(module, "errors", None)
        not_found_types = tuple(
            value
            for value in (
                getattr(errors, "RepositoryNotFoundError", None),
                getattr(errors, "RevisionNotFoundError", None),
            )
            if isinstance(value, type)
        )
        gated_type = getattr(errors, "GatedRepoError", None)
        if isinstance(gated_type, type) and isinstance(error, gated_type):
            return revision_error("MODEL_ACCESS_DENIED", context)
        if not_found_types and isinstance(error, not_found_types):
            return revision_error("MODEL_SELECTION_INVALID", context)
        return ApplicationError(
            "MODEL_CATALOG_UNAVAILABLE",
            ErrorCategory.TRANSIENT_NETWORK,
            True,
            "Hugging Face 모델 카탈로그에 연결할 수 없습니다.",
            context,
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

    @staticmethod
    def _physical_memory() -> int | None:
        try:
            pages = os.sysconf("SC_PHYS_PAGES")
            page_size = os.sysconf("SC_PAGE_SIZE")
        except (AttributeError, OSError, ValueError):
            return None
        if not isinstance(pages, int) or not isinstance(page_size, int):
            return None
        return pages * page_size if pages > 0 and page_size > 0 else None
