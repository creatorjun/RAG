from __future__ import annotations

from enterprise_rag.application.dto.job_result import (
    CompletionNotificationDto,
    CompletionNotificationState,
)
from enterprise_rag.application.ports.clock import ClockPort
from enterprise_rag.application.ports.completion_notification import (
    CompletionNotificationReceiptPort,
    SystemNotificationPort,
)
from enterprise_rag.application.ports.job_repository import DocumentJobRepositoryPort
from enterprise_rag.application.ports.job_result import DocumentJobResultReaderPort
from enterprise_rag.application.services.completion_notification_status import (
    CompletionNotificationStatusService,
)
from enterprise_rag.domain.errors import ApplicationError


class GetCompletionNotificationStatus:
    def __init__(
        self,
        jobs: DocumentJobRepositoryPort,
        results: DocumentJobResultReaderPort,
        receipts: CompletionNotificationReceiptPort,
    ) -> None:
        self._status = CompletionNotificationStatusService(jobs, results, receipts)

    async def execute(self, job_id: str) -> CompletionNotificationDto:
        return (await self._status.assess(job_id)).status


class NotifyDocumentJobCompletion:
    def __init__(
        self,
        jobs: DocumentJobRepositoryPort,
        results: DocumentJobResultReaderPort,
        receipts: CompletionNotificationReceiptPort,
        notifier: SystemNotificationPort,
        clock: ClockPort,
    ) -> None:
        self._status = CompletionNotificationStatusService(jobs, results, receipts)
        self._receipts = receipts
        self._notifier = notifier
        self._clock = clock

    async def execute(self, job_id: str) -> CompletionNotificationDto:
        assessment = await self._status.assess(job_id)
        status = assessment.status
        if status.state is not CompletionNotificationState.READY:
            return status
        result = assessment.result
        if result is None:
            return CompletionNotificationDto(job_id, CompletionNotificationState.NOT_READY)
        fingerprint = result.publication_fingerprint
        if fingerprint is None:
            return CompletionNotificationDto(job_id, CompletionNotificationState.NOT_READY)
        claim = await self._receipts.claim(job_id, fingerprint, self._clock.now())
        if not claim.acquired:
            return claim.receipt
        try:
            await self._notifier.send(
                "Local Document RAG 작업 완료",
                f"{job_id} 문서 게시와 품질 검증이 완료되었습니다.",
            )
        except ApplicationError as error:
            return await self._receipts.finish(
                job_id,
                fingerprint,
                self._clock.now(),
                error.code,
            )
        except Exception:
            return await self._receipts.finish(
                job_id,
                fingerprint,
                self._clock.now(),
                "NOTIFICATION_FAILED",
            )
        return await self._receipts.finish(
            job_id,
            fingerprint,
            self._clock.now(),
        )
