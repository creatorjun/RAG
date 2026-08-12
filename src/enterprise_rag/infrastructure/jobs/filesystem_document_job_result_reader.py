from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, cast

from enterprise_rag.application.dto.job_result import (
    ComparisonCountsDto,
    DocumentJobResultDto,
    JobResultAvailability,
)
from enterprise_rag.application.dto.tasks import FinalQualityReportDto
from enterprise_rag.application.ports.final_document_repository import (
    FinalDocumentRepositoryPort,
)
from enterprise_rag.application.ports.job_artifacts import JobArtifactRepositoryPort
from enterprise_rag.application.ports.job_definition_repository import (
    DocumentJobDefinitionRepositoryPort,
)
from enterprise_rag.domain.errors import ApplicationError, revision_error
from enterprise_rag.domain.jobs import DocumentJob
from enterprise_rag.infrastructure.workspace.file_io import sha256_file
from enterprise_rag.infrastructure.workspace.path_security import (
    is_link_or_reparse,
    is_within,
    validate_tree,
)

_QUALITY_PATH = "control/final-validation.json"
_PUBLISH_PATH = "control/publish-result.json"


class FilesystemDocumentJobResultReader:
    def __init__(
        self,
        var_root: Path,
        artifacts: JobArtifactRepositoryPort,
        definitions: DocumentJobDefinitionRepositoryPort,
        finals: FinalDocumentRepositoryPort,
    ) -> None:
        self._jobs_root = (var_root / "jobs").resolve(strict=True)
        self._artifacts = artifacts
        self._definitions = definitions
        self._finals = finals

    async def inspect(self, job: DocumentJob) -> DocumentJobResultDto:
        definition = await self._definitions.load(job.job_id)
        execution = definition.request.execution_settings
        if execution is None:
            raise revision_error("JOB_DEFINITION_INVALID", {"job_id": job.job_id})
        notification_enabled = execution.notify_on_completion
        try:
            await self._artifacts.read_json(job.job_id, _QUALITY_PATH)
        except ApplicationError as error:
            if error.code == "JOB_ARTIFACT_NOT_FOUND":
                return DocumentJobResultDto(
                    job.job_id,
                    job.state,
                    JobResultAvailability.NOT_READY,
                    notification_enabled,
                )
            raise
        try:
            candidate = await self._finals.load(job.job_id)
            quality_path = self._artifact_path(job.job_id, _QUALITY_PATH)
            try:
                published = await self._artifacts.read_json(job.job_id, _PUBLISH_PATH)
            except ApplicationError as error:
                if error.code == "JOB_ARTIFACT_NOT_FOUND":
                    return DocumentJobResultDto(
                        job.job_id,
                        job.state,
                        JobResultAvailability.QUALITY_READY,
                        notification_enabled,
                        candidate.quality,
                        quality_report_path=str(quality_path),
                    )
                raise
            return self._published_result(
                job,
                definition.request.output_relative_path,
                Path(execution.output_root),
                notification_enabled,
                candidate.quality,
                quality_path,
                published,
            )
        except ApplicationError:
            raise
        except (KeyError, OSError, TypeError, ValueError) as error:
            raise revision_error("JOB_RESULT_INVALID", {"job_id": job.job_id}) from error

    def _published_result(
        self,
        job: DocumentJob,
        output_relative_path: str,
        output_root: Path,
        notification_enabled: bool,
        quality: FinalQualityReportDto,
        quality_path: Path,
        published: dict[str, Any],
    ) -> DocumentJobResultDto:
        base_fields = {
            "schema_version",
            "job_id",
            "run_id",
            "output_relative_path",
            "comparison_report_sha256",
            "file_count",
            "counts",
        }
        digest_fields = {
            "document_sha256",
            "comparison_markdown_sha256",
            "synthesis_report_sha256",
        }
        actual_fields = set(published)
        if (
            (actual_fields != base_fields and actual_fields != base_fields | digest_fields)
            or published["schema_version"] != 1
            or published["job_id"] != job.job_id
            or published["run_id"] != job.job_id
            or published["output_relative_path"] != output_relative_path
        ):
            raise ValueError("invalid publish result envelope")
        report_digest = self._string(published["comparison_report_sha256"])
        file_count = self._integer(published["file_count"])
        counts = self._counts(published["counts"])
        if file_count < 1 or counts.total != file_count:
            raise ValueError("publish result count mismatch")

        if is_link_or_reparse(output_root):
            raise ValueError("output root cannot be a link")
        resolved_output = output_root.expanduser().resolve(strict=True)
        run_root = (resolved_output / "runs" / job.job_id).resolve(strict=True)
        if is_link_or_reparse(run_root) or not is_within(run_root, resolved_output):
            raise ValueError("published run escaped output root")
        validate_tree(run_root)
        document = self._file(run_root, Path("documents") / output_relative_path)
        comparison_json = self._file(run_root, Path("_reports/comparison.json"))
        comparison_markdown = self._file(run_root, Path("_reports/comparison.md"))
        synthesis_report = self._file(run_root, Path("_reports/synthesis.json"))
        if sha256_file(document) != quality.document_sha256:
            raise ValueError("published document digest mismatch")
        if sha256_file(comparison_json) != report_digest:
            raise ValueError("comparison report digest mismatch")
        if digest_fields.issubset(published):
            if (
                self._string(published["document_sha256"]) != quality.document_sha256
                or self._string(published["comparison_markdown_sha256"])
                != sha256_file(comparison_markdown)
                or self._string(published["synthesis_report_sha256"])
                != sha256_file(synthesis_report)
            ):
                raise ValueError("published auxiliary report digest mismatch")
        actual_comparison = self._json_file(comparison_json)
        if (
            actual_comparison.get("schema_version") != 1
            or actual_comparison.get("run_id") != job.job_id
            or self._counts(actual_comparison.get("counts")) != counts
        ):
            raise ValueError("comparison report content mismatch")
        fingerprint_payload = {
            "job_id": job.job_id,
            "document_sha256": quality.document_sha256,
            "comparison_report_sha256": report_digest,
            "counts": {
                "added": counts.added,
                "modified": counts.modified,
                "removed": counts.removed,
                "unchanged": counts.unchanged,
            },
        }
        fingerprint = hashlib.sha256(
            json.dumps(
                fingerprint_payload,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
        return DocumentJobResultDto(
            job.job_id,
            job.state,
            JobResultAvailability.PUBLISHED,
            notification_enabled,
            quality,
            str(document),
            str(quality_path),
            str(comparison_json),
            str(comparison_markdown),
            str(synthesis_report),
            counts,
            report_digest,
            fingerprint,
        )

    def _artifact_path(self, job_id: str, relative: str) -> Path:
        candidate = self._jobs_root / job_id / relative
        if is_link_or_reparse(candidate):
            raise ValueError("job result artifact cannot be a link")
        resolved = candidate.resolve(strict=True)
        if not resolved.is_file() or not is_within(resolved, self._jobs_root):
            raise ValueError("job result artifact escaped jobs root")
        return resolved

    @staticmethod
    def _file(root: Path, relative: Path) -> Path:
        candidate = root / relative
        if is_link_or_reparse(candidate):
            raise ValueError("published result cannot be a link")
        resolved = candidate.resolve(strict=True)
        if not resolved.is_file() or not is_within(resolved, root):
            raise ValueError("published result escaped run root")
        return resolved

    @staticmethod
    def _json_file(path: Path) -> dict[str, Any]:
        value = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(value, dict):
            raise ValueError("expected JSON object")
        return cast(dict[str, Any], value)

    @classmethod
    def _counts(cls, value: Any) -> ComparisonCountsDto:
        if not isinstance(value, dict) or set(value) != {
            "added",
            "modified",
            "removed",
            "unchanged",
        }:
            raise ValueError("invalid comparison counts")
        return ComparisonCountsDto(
            cls._integer(value["added"]),
            cls._integer(value["modified"]),
            cls._integer(value["removed"]),
            cls._integer(value["unchanged"]),
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
