from __future__ import annotations

import re

from enterprise_rag.application.dto.job_dashboard import (
    CheckpointStatus,
    JobCheckpointDto,
)
from enterprise_rag.application.ports.claim_draft_repository import (
    ClaimDraftRepositoryPort,
)
from enterprise_rag.application.ports.claim_ledger_repository import (
    ClaimLedgerRepositoryPort,
)
from enterprise_rag.application.ports.evidence_repository import EvidenceRepositoryPort
from enterprise_rag.application.ports.final_document_repository import (
    FinalDocumentRepositoryPort,
)
from enterprise_rag.application.ports.job_artifacts import JobArtifactRepositoryPort
from enterprise_rag.application.ports.task_plan_repository import TaskPlanRepositoryPort
from enterprise_rag.application.ports.task_result_repository import (
    TaskResultRepositoryPort,
)
from enterprise_rag.domain.errors import ApplicationError

_ATTEMPT_PATH = re.compile(
    r"^tasks/([a-z0-9][a-z0-9-]{1,62}[a-z0-9])/attempt-([0-9]{3})/"
    r"(output|validation)\.json$"
)
_SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
_CLAIM_DRAFT_PATH = re.compile(r"^claim-drafts/([0-9a-f]{64})\.json$")


class FilesystemJobCheckpointInspector:
    def __init__(
        self,
        artifacts: JobArtifactRepositoryPort,
        evidence: EvidenceRepositoryPort,
        claims: ClaimLedgerRepositoryPort,
        plans: TaskPlanRepositoryPort,
        results: TaskResultRepositoryPort,
        finals: FinalDocumentRepositoryPort,
        claim_drafts: ClaimDraftRepositoryPort | None = None,
    ) -> None:
        self._artifacts = artifacts
        self._evidence = evidence
        self._claims = claims
        self._plans = plans
        self._results = results
        self._finals = finals
        self._claim_drafts = claim_drafts

    async def inspect(self, job_id: str) -> tuple[JobCheckpointDto, ...]:
        return (
            await self._definition(job_id),
            await self._source_manifest(job_id),
            await self._evidence_checkpoint(job_id),
            await self._claim_drafts_checkpoint(job_id),
            await self._claim_checkpoint(job_id),
            await self._task_plan_checkpoint(job_id),
            await self._task_attempts_checkpoint(job_id),
            await self._draft_checkpoint(job_id),
            await self._final_checkpoint(job_id),
            await self._published_checkpoint(job_id),
        )

    async def _definition(self, job_id: str) -> JobCheckpointDto:
        try:
            value = await self._artifacts.read_json(job_id, "definition.json")
            if value.get("schema_version") != 1 or value.get("job_id") != job_id:
                raise ValueError("definition envelope mismatch")
            fingerprint = value.get("pipeline_fingerprint")
            if not isinstance(fingerprint, str) or not _SHA256_PATTERN.fullmatch(
                fingerprint
            ):
                raise ValueError("definition fingerprint missing")
            return self._saved(
                "definition",
                "Job 정의",
                "definition.json",
                1,
                f"pipeline {fingerprint[:12]}…",
            )
        except ApplicationError as error:
            return self._from_error("definition", "Job 정의", "definition.json", error)
        except (TypeError, ValueError):
            return self._invalid("definition", "Job 정의", "definition.json")

    async def _source_manifest(self, job_id: str) -> JobCheckpointDto:
        path = "source-manifest.json"
        try:
            value = await self._artifacts.read_json(job_id, path)
            if value.get("schema_version") != 1 or value.get("job_id") != job_id:
                raise ValueError("source manifest envelope mismatch")
            files = value.get("files")
            if not isinstance(files, list):
                raise ValueError("source manifest files missing")
            paths: set[str] = set()
            for item in files:
                if not isinstance(item, dict):
                    raise ValueError("source manifest item invalid")
                relative_path = item.get("relative_path")
                digest = item.get("source_sha256")
                byte_count = item.get("byte_count")
                if (
                    not isinstance(relative_path, str)
                    or not relative_path
                    or relative_path in paths
                    or not isinstance(digest, str)
                    or not _SHA256_PATTERN.fullmatch(digest)
                    or isinstance(byte_count, bool)
                    or not isinstance(byte_count, int)
                    or byte_count < 0
                ):
                    raise ValueError("source manifest item invalid")
                paths.add(relative_path)
            return self._saved(
                "source_manifest", "원본 manifest", path, len(files), "파일 hash 검증됨"
            )
        except ApplicationError as error:
            return self._from_error("source_manifest", "원본 manifest", path, error)
        except (TypeError, ValueError):
            return self._invalid("source_manifest", "원본 manifest", path)

    async def _evidence_checkpoint(self, job_id: str) -> JobCheckpointDto:
        path = "evidence/index.json"
        try:
            bundle = await self._evidence.load(job_id)
            return self._saved(
                "evidence",
                "Evidence",
                path,
                len(bundle.items),
                f"구조 coverage {len(bundle.items)}/{bundle.source_structure_count}",
            )
        except ApplicationError as error:
            return self._from_error("evidence", "Evidence", path, error)

    async def _claim_checkpoint(self, job_id: str) -> JobCheckpointDto:
        path = "control/claim-ledger.json"
        try:
            ledger = await self._claims.load(job_id)
            return self._saved(
                "claim_ledger",
                "Claim Ledger",
                path,
                len(ledger.claims),
                f"관계 {len(ledger.relations)}건",
            )
        except ApplicationError as error:
            return self._from_error("claim_ledger", "Claim Ledger", path, error)

    async def _claim_drafts_checkpoint(self, job_id: str) -> JobCheckpointDto:
        path = "claim-drafts/"
        try:
            paths = await self._artifacts.list_relative_paths(job_id, "claim-drafts")
            evidence = await self._evidence.load(job_id)
        except ApplicationError as error:
            return self._from_error("claim_drafts", "Claim 추출", path, error)
        if not paths:
            return self._missing("claim_drafts", "Claim 추출", path)
        expected_digests = {
            item.evidence_id.removeprefix("evidence:sha256:")
            for item in evidence.items
        }
        digests: set[str] = set()
        try:
            for relative_path in paths:
                match = _CLAIM_DRAFT_PATH.fullmatch(relative_path)
                if (
                    match is None
                    or match.group(1) in digests
                    or match.group(1) not in expected_digests
                ):
                    raise ValueError("claim draft path is invalid")
                digest = match.group(1)
                digests.add(digest)
                if self._claim_drafts is not None:
                    await self._claim_drafts.load(
                        job_id,
                        "evidence:sha256:" + digest,
                    )
        except (ApplicationError, ValueError):
            return self._invalid("claim_drafts", "Claim 추출", path)
        completed = len(digests)
        total = len(evidence.items)
        if completed > total or not digests.issubset(expected_digests):
            return self._invalid("claim_drafts", "Claim 추출", path)
        if completed < total:
            return JobCheckpointDto(
                "claim_drafts",
                "Claim 추출",
                path,
                CheckpointStatus.IN_PROGRESS,
                completed,
                completed > 0,
                f"Evidence {completed}/{total}건 저장 · 중단 시 여기부터 재개",
            )
        return self._saved(
            "claim_drafts",
            "Claim 추출",
            path,
            completed,
            f"Evidence {completed}/{total}건 추출 완료",
        )

    async def _task_plan_checkpoint(self, job_id: str) -> JobCheckpointDto:
        path = "control/task-plan.json"
        try:
            plan = await self._plans.load(job_id)
            return self._saved(
                "task_plan",
                "Task plan",
                path,
                len(plan.tasks),
                (
                    f"Claim {plan.coverage.source_claim_count}, "
                    f"Evidence {plan.coverage.source_evidence_count} 배정"
                ),
            )
        except ApplicationError as error:
            return self._from_error("task_plan", "Task plan", path, error)

    async def _task_attempts_checkpoint(self, job_id: str) -> JobCheckpointDto:
        try:
            paths = await self._artifacts.list_relative_paths(job_id, "tasks")
        except ApplicationError as error:
            return self._from_error("task_attempts", "Task attempts", "tasks/", error)
        if not paths:
            return self._missing("task_attempts", "Task attempts", "tasks/")
        grouped: dict[tuple[str, int], set[str]] = {}
        for path in paths:
            match = _ATTEMPT_PATH.fullmatch(path)
            if match is None:
                return self._invalid("task_attempts", "Task attempts", "tasks/")
            task_id, raw_attempt, kind = match.groups()
            attempt = int(raw_attempt)
            if not 1 <= attempt <= 3:
                return self._invalid("task_attempts", "Task attempts", "tasks/")
            grouped.setdefault((task_id, attempt), set()).add(kind)
        valid_count = 0
        incomplete = False
        try:
            for (task_id, attempt), kinds in sorted(grouped.items()):
                if kinds != {"output", "validation"}:
                    incomplete = True
                    continue
                await self._results.load_output(job_id, task_id, attempt)
                await self._results.load_validation(job_id, task_id, attempt)
                valid_count += 1
        except ApplicationError:
            return self._invalid("task_attempts", "Task attempts", "tasks/")
        if incomplete:
            return JobCheckpointDto(
                "task_attempts",
                "Task attempts",
                "tasks/",
                CheckpointStatus.IN_PROGRESS,
                valid_count,
                valid_count > 0,
                f"검증 저장 {valid_count}건, 미완료 attempt 있음",
            )
        return self._saved(
            "task_attempts",
            "Task attempts",
            "tasks/",
            valid_count,
            f"완전한 attempt {valid_count}건",
        )

    async def _draft_checkpoint(self, job_id: str) -> JobCheckpointDto:
        path = "derived/assembled-draft.md"
        try:
            value = await self._artifacts.read_text(job_id, path)
            if not value.startswith("# "):
                raise ValueError("draft heading missing")
            return self._saved("assembled_draft", "조립 초안", path, 1, "Markdown 읽기 검증됨")
        except ApplicationError as error:
            return self._from_error("assembled_draft", "조립 초안", path, error)
        except ValueError:
            return self._invalid("assembled_draft", "조립 초안", path)

    async def _final_checkpoint(self, job_id: str) -> JobCheckpointDto:
        path = "control/final-validation.json"
        try:
            # Read the report first so a missing report remains distinguishable from
            # a present but corrupt report or a report whose draft digest does not match.
            await self._artifacts.read_json(job_id, path)
            candidate = await self._finals.load(job_id)
            status = CheckpointStatus.SAVED if candidate.quality.valid else CheckpointStatus.INVALID
            return JobCheckpointDto(
                "final_quality",
                "최종 품질 게이트",
                path,
                status,
                candidate.quality.validated_task_count,
                candidate.quality.valid,
                (
                    "통과"
                    if candidate.quality.valid
                    else ", ".join(candidate.quality.error_codes)
                ),
            )
        except ApplicationError as error:
            return self._from_error("final_quality", "최종 품질 게이트", path, error)

    async def _published_checkpoint(self, job_id: str) -> JobCheckpointDto:
        path = "control/publish-result.json"
        try:
            value = await self._artifacts.read_json(job_id, path)
            report_digest = value.get("comparison_report_sha256")
            file_count = value.get("file_count")
            if (
                value.get("schema_version") != 1
                or value.get("job_id") != job_id
                or value.get("run_id") != job_id
                or not isinstance(report_digest, str)
                or not _SHA256_PATTERN.fullmatch(report_digest)
                or isinstance(file_count, bool)
                or not isinstance(file_count, int)
                or file_count < 1
            ):
                raise ValueError("publish result invalid")
            return JobCheckpointDto(
                "published_run",
                "게시 run",
                path,
                CheckpointStatus.SAVED,
                file_count,
                False,
                f"비교 보고서 {report_digest[:12]}…",
            )
        except ApplicationError as error:
            return self._from_error("published_run", "게시 run", path, error)
        except (TypeError, ValueError):
            return self._invalid("published_run", "게시 run", path)

    @staticmethod
    def _saved(
        checkpoint_id: str,
        label: str,
        path: str,
        count: int,
        detail: str,
    ) -> JobCheckpointDto:
        return JobCheckpointDto(
            checkpoint_id, label, path, CheckpointStatus.SAVED, count, True, detail
        )

    @staticmethod
    def _missing(checkpoint_id: str, label: str, path: str) -> JobCheckpointDto:
        return JobCheckpointDto(
            checkpoint_id,
            label,
            path,
            CheckpointStatus.MISSING,
            None,
            False,
            "아직 저장되지 않음",
        )

    @classmethod
    def _from_error(
        cls,
        checkpoint_id: str,
        label: str,
        path: str,
        error: ApplicationError,
    ) -> JobCheckpointDto:
        if error.code == "JOB_ARTIFACT_NOT_FOUND":
            return cls._missing(checkpoint_id, label, path)
        return cls._invalid(checkpoint_id, label, path)

    @staticmethod
    def _invalid(checkpoint_id: str, label: str, path: str) -> JobCheckpointDto:
        return JobCheckpointDto(
            checkpoint_id,
            label,
            path,
            CheckpointStatus.INVALID,
            None,
            False,
            "파일 또는 무결성 검증 실패",
        )
