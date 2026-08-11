# src/enterprise_rag/infrastructure/workspace/folder_revision_workspace.py
from __future__ import annotations

import asyncio
import json
import shutil
from collections.abc import Callable
from pathlib import Path, PurePosixPath
from typing import Any, TypeVar

from enterprise_rag.application.dto.revision import (
    FolderComparisonDto,
    GeneratedDocumentWriteDto,
    RevisionRunDto,
)
from enterprise_rag.application.ports.clock import ClockPort, IdGeneratorPort
from enterprise_rag.application.ports.document_workspace import DocumentComparatorPort
from enterprise_rag.domain.errors import ApplicationError, revision_error
from enterprise_rag.domain.revision import RevisionRunState
from enterprise_rag.infrastructure.workspace.file_io import (
    atomic_write_json,
    atomic_write_text,
    sha256_file,
)
from enterprise_rag.infrastructure.workspace.path_security import (
    is_link_or_reparse,
    is_within,
    resolve_existing_root,
    validate_non_overlapping,
    validate_tree,
)

_Result = TypeVar("_Result")


class FolderRevisionWorkspace:
    def __init__(
        self,
        before_root: Path,
        after_root: Path,
        comparator: DocumentComparatorPort,
        clock: ClockPort,
        id_generator: IdGeneratorPort,
        max_file_bytes: int,
    ) -> None:
        self._before_root = resolve_existing_root(before_root, before=True)
        self._after_root = resolve_existing_root(after_root, before=False)
        validate_non_overlapping(self._before_root, self._after_root)
        self._comparator = comparator
        self._clock = clock
        self._id_generator = id_generator
        self._max_file_bytes = max_file_bytes

    async def prepare_run(self, run_id: str) -> RevisionRunDto:
        return await self._run_io(self._prepare_run, run_id)

    async def compare_run(self, run_id: str) -> FolderComparisonDto:
        return await self._run_io(self._compare_run, run_id)

    async def finalize_run(self, run_id: str) -> RevisionRunDto:
        return await self._run_io(self._finalize_run, run_id)

    async def write_generated_document(
        self,
        run_id: str,
        request: GeneratedDocumentWriteDto,
    ) -> str:
        try:
            return await asyncio.to_thread(self._write_generated_document, run_id, request)
        except ApplicationError:
            raise
        except (OSError, json.JSONDecodeError, TypeError, ValueError) as error:
            raise revision_error("IO_FAILURE", {"run_id": run_id}) from error

    async def _run_io(self, operation: Callable[[str], _Result], run_id: str) -> _Result:
        try:
            return await asyncio.to_thread(operation, run_id)
        except ApplicationError:
            raise
        except (OSError, json.JSONDecodeError, TypeError, ValueError) as error:
            raise revision_error("IO_FAILURE", {"run_id": run_id}) from error

    def _prepare_run(self, run_id: str) -> RevisionRunDto:
        validate_tree(self._before_root)
        entries = self._inventory(self._before_root)
        runs_root = self._after_root / "runs"
        staging_root = self._after_root / ".staging"
        runs_root.mkdir(parents=True, exist_ok=True)
        staging_root.mkdir(parents=True, exist_ok=True)
        target = runs_root / run_id
        if target.exists() or is_link_or_reparse(target):
            raise revision_error("RUN_ALREADY_EXISTS", {"run_id": run_id})
        temporary = staging_root / f"{run_id}-{self._id_generator.new_id()}"
        documents_root = temporary / "documents"
        reports_root = temporary / "_reports"
        documents_root.mkdir(parents=True, exist_ok=False)
        reports_root.mkdir(parents=True, exist_ok=False)
        try:
            self._copy_inventory(entries, documents_root)
            if self._inventory(self._before_root) != entries:
                raise revision_error("INPUT_HASH_CHANGED", {"run_id": run_id})
            prepared_at = self._utc_now()
            input_manifest = {
                "schema_version": 1,
                "run_id": run_id,
                "captured_at": prepared_at,
                "file_count": len(entries),
                "files": entries,
            }
            input_manifest_path = reports_root / "input-manifest.json"
            atomic_write_json(input_manifest_path, input_manifest)
            manifest = {
                "schema_version": 1,
                "run_id": run_id,
                "state": RevisionRunState.PREPARED.value,
                "prepared_at": prepared_at,
                "finalized_at": None,
                "input_file_count": len(entries),
                "input_manifest_sha256": sha256_file(input_manifest_path),
            }
            atomic_write_json(temporary / "run-manifest.json", manifest)
            try:
                temporary.replace(target)
            except OSError as error:
                if target.exists():
                    raise revision_error("RUN_ALREADY_EXISTS", {"run_id": run_id}) from error
                raise
        finally:
            if temporary.exists():
                shutil.rmtree(temporary)
        return self._to_run_dto(target, self._read_manifest(target, run_id))

    def _compare_run(self, run_id: str) -> FolderComparisonDto:
        run_root, manifest = self._open_prepared_run(run_id)
        documents_root = (run_root / "documents").resolve(strict=True)
        reports_root = (run_root / "_reports").resolve(strict=True)
        input_manifest_path = reports_root / "input-manifest.json"
        self._verify_input_manifest(input_manifest_path)
        before_signature = self._content_signature(self._before_root)
        documents_signature = self._content_signature(documents_root)
        timestamp = self._clock.now().strftime("%Y%m%d%H%M%S")
        comparison_id = f"cmp-{timestamp}-{self._id_generator.new_id()[:12]}"
        report = self._comparator.compare(
            self._before_root,
            documents_root,
            reports_root,
            run_id,
            comparison_id,
            self._utc_now(),
        )
        if self._content_signature(self._before_root) != before_signature:
            raise revision_error("INPUT_HASH_CHANGED", {"run_id": run_id})
        if self._content_signature(documents_root) != documents_signature:
            raise revision_error("COMPARISON_INCOMPLETE", {"run_id": run_id})
        if manifest["input_manifest_sha256"] != sha256_file(input_manifest_path):
            raise revision_error("INPUT_HASH_CHANGED", {"run_id": run_id})
        return report

    def _finalize_run(self, run_id: str) -> RevisionRunDto:
        report = self._compare_run(run_id)
        run_root, manifest = self._open_prepared_run(run_id)
        reports_root = run_root / "_reports"
        comparison_path = reports_root / "comparison.json"
        if not comparison_path.is_file() or sha256_file(comparison_path) != report.report_sha256:
            raise revision_error("COMPARISON_INCOMPLETE", {"run_id": run_id})
        self._verify_input_manifest(reports_root / "input-manifest.json")
        self._verify_synthesis_manifest(run_root, run_id)
        manifest["state"] = RevisionRunState.FINALIZED.value
        manifest["finalized_at"] = self._utc_now()
        manifest["comparison_counts"] = report.counts
        manifest["comparison_sha256"] = report.report_sha256
        atomic_write_json(run_root / "run-manifest.json", manifest)
        return self._to_run_dto(run_root, manifest)

    def _write_generated_document(
        self,
        run_id: str,
        request: GeneratedDocumentWriteDto,
    ) -> str:
        run_root, _ = self._open_prepared_run(run_id)
        documents_root = (run_root / "documents").resolve(strict=True)
        relative = self._validate_output_relative_path(request.relative_path)
        target = documents_root.joinpath(*relative.parts)
        current = documents_root
        for part in relative.parts[:-1]:
            current = current / part
            if current.exists() and is_link_or_reparse(current):
                raise revision_error("LINK_NOT_ALLOWED", {"relative_path": relative.as_posix()})
        if target.exists() or is_link_or_reparse(target):
            raise revision_error(
                "OUTPUT_ALREADY_EXISTS",
                {"relative_path": relative.as_posix()},
            )
        target.parent.mkdir(parents=True, exist_ok=True)
        if not is_within(target.parent.resolve(strict=True), documents_root):
            raise revision_error("PATH_ESCAPE", {"relative_path": relative.as_posix()})
        atomic_write_text(target, request.content)
        report_path = run_root / "_reports" / "synthesis.json"
        if report_path.exists() or is_link_or_reparse(report_path):
            raise revision_error(
                "OUTPUT_ALREADY_EXISTS",
                {"relative_path": "_reports/synthesis.json"},
            )
        atomic_write_json(
            report_path,
            {
                "schema_version": 1,
                "run_id": run_id,
                "generated_at": self._utc_now(),
                "output_relative_path": relative.as_posix(),
                "output_sha256": sha256_file(target),
                "model_id": request.model_id,
                "model_revision": request.model_revision,
                "source_document_count": len(request.sources),
                "source_chunk_count": request.source_chunk_count,
                "generation_count": request.generation_count,
                "sources": [
                    {
                        "relative_path": source.relative_path,
                        "source_sha256": source.source_sha256,
                    }
                    for source in request.sources
                ],
            },
        )
        return relative.as_posix()

    def _open_prepared_run(self, run_id: str) -> tuple[Path, dict[str, Any]]:
        candidate = self._after_root / "runs" / run_id
        if is_link_or_reparse(candidate):
            raise revision_error("LINK_NOT_ALLOWED", {"run_id": run_id})
        try:
            run_root = candidate.resolve(strict=True)
        except FileNotFoundError as error:
            raise revision_error("RUN_NOT_FOUND", {"run_id": run_id}) from error
        if not is_within(run_root, self._after_root):
            raise revision_error("PATH_ESCAPE", {"run_id": run_id})
        validate_tree(run_root)
        manifest = self._read_manifest(run_root, run_id)
        if manifest["state"] == RevisionRunState.FINALIZED.value:
            raise revision_error("RUN_FINALIZED", {"run_id": run_id})
        if manifest["state"] != RevisionRunState.PREPARED.value:
            raise revision_error("COMPARISON_INCOMPLETE", {"run_id": run_id})
        for name in ("documents", "_reports"):
            path = run_root / name
            if is_link_or_reparse(path) or not path.is_dir():
                raise revision_error("LINK_NOT_ALLOWED", {"run_id": run_id})
        return run_root, manifest

    def _read_manifest(self, run_root: Path, run_id: str) -> dict[str, Any]:
        manifest_path = run_root / "run-manifest.json"
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError, UnicodeDecodeError) as error:
            raise revision_error("COMPARISON_INCOMPLETE", {"run_id": run_id}) from error
        required = {
            "run_id",
            "state",
            "prepared_at",
            "finalized_at",
            "input_file_count",
            "input_manifest_sha256",
        }
        if not isinstance(manifest, dict) or not required.issubset(manifest):
            raise revision_error("COMPARISON_INCOMPLETE", {"run_id": run_id})
        if manifest["run_id"] != run_id:
            raise revision_error("COMPARISON_INCOMPLETE", {"run_id": run_id})
        return manifest

    def _verify_input_manifest(self, manifest_path: Path) -> None:
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            files = manifest["files"]
            expected = {
                entry["relative_path"]: (entry["byte_count"], entry["sha256"]) for entry in files
            }
        except (KeyError, TypeError, json.JSONDecodeError, UnicodeDecodeError) as error:
            raise revision_error("COMPARISON_INCOMPLETE") from error
        if manifest.get("file_count") != len(expected):
            raise revision_error("COMPARISON_INCOMPLETE")
        if self._content_signature(self._before_root) != expected:
            raise revision_error("INPUT_HASH_CHANGED")

    def _verify_synthesis_manifest(self, run_root: Path, run_id: str) -> None:
        report_path = run_root / "_reports" / "synthesis.json"
        if not report_path.exists():
            return
        try:
            report = json.loads(report_path.read_text(encoding="utf-8"))
            relative = self._validate_output_relative_path(report["output_relative_path"])
            expected_sha256 = str(report["output_sha256"])
        except (KeyError, TypeError, json.JSONDecodeError, UnicodeDecodeError) as error:
            raise revision_error("COMPARISON_INCOMPLETE", {"run_id": run_id}) from error
        candidate = run_root / "documents" / relative
        if is_link_or_reparse(candidate):
            raise revision_error("LINK_NOT_ALLOWED", {"run_id": run_id})
        try:
            output_path = candidate.resolve(strict=True)
        except FileNotFoundError as error:
            raise revision_error("COMPARISON_INCOMPLETE", {"run_id": run_id}) from error
        documents_root = (run_root / "documents").resolve(strict=True)
        if not output_path.is_file() or not is_within(output_path, documents_root):
            raise revision_error("PATH_ESCAPE", {"run_id": run_id})
        if sha256_file(output_path) != expected_sha256:
            raise revision_error("COMPARISON_INCOMPLETE", {"run_id": run_id})

    def _inventory(self, root: Path) -> list[dict[str, Any]]:
        validate_tree(root)
        entries: list[dict[str, Any]] = []
        for path in sorted(root.rglob("*"), key=lambda item: item.as_posix()):
            if not path.is_file():
                continue
            relative = path.relative_to(root).as_posix()
            byte_count = path.stat().st_size
            if byte_count > self._max_file_bytes:
                raise revision_error("IO_FAILURE", {"relative_path": relative})
            entries.append(
                {
                    "relative_path": relative,
                    "byte_count": byte_count,
                    "sha256": sha256_file(path),
                }
            )
        return entries

    def _copy_inventory(self, entries: list[dict[str, Any]], documents_root: Path) -> None:
        for entry in entries:
            relative_path = str(entry["relative_path"])
            source = self._before_root / relative_path
            destination = documents_root / relative_path
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, destination)
            if sha256_file(destination) != entry["sha256"]:
                raise revision_error("INPUT_HASH_CHANGED", {"relative_path": relative_path})

    def _content_signature(self, root: Path) -> dict[str, tuple[int, str]]:
        return {
            entry["relative_path"]: (entry["byte_count"], entry["sha256"])
            for entry in self._inventory(root)
        }

    def _utc_now(self) -> str:
        return self._clock.now().isoformat().replace("+00:00", "Z")

    @staticmethod
    def _validate_output_relative_path(value: str) -> PurePosixPath:
        if not value or "\\" in value or "\x00" in value:
            raise revision_error("PATH_ESCAPE")
        path = PurePosixPath(value)
        if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
            raise revision_error("PATH_ESCAPE", {"relative_path": value})
        if path.suffix.lower() != ".md":
            raise revision_error("TEXT_FORMAT_UNSUPPORTED", {"relative_path": value})
        return path

    @staticmethod
    def _to_run_dto(run_root: Path, manifest: dict[str, Any]) -> RevisionRunDto:
        return RevisionRunDto(
            run_id=str(manifest["run_id"]),
            state=RevisionRunState(str(manifest["state"])),
            input_manifest_sha256=str(manifest["input_manifest_sha256"]),
            input_file_count=int(manifest["input_file_count"]),
            documents_relative_root=f"runs/{manifest['run_id']}/documents",
            prepared_at=str(manifest["prepared_at"]),
            finalized_at=(str(manifest["finalized_at"]) if manifest["finalized_at"] else None),
        )
