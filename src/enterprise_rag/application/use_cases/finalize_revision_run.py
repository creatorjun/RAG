# src/enterprise_rag/application/use_cases/finalize_revision_run.py
from enterprise_rag.application.dto.revision import RevisionRunDto
from enterprise_rag.application.ports.document_workspace import DocumentWorkspacePort
from enterprise_rag.domain.errors import revision_error
from enterprise_rag.domain.value_objects import RunId


class FinalizeRevisionRun:
    def __init__(self, workspace: DocumentWorkspacePort) -> None:
        self._workspace = workspace

    async def execute(self, run_id: str) -> RevisionRunDto:
        try:
            validated = RunId(run_id)
        except ValueError as error:
            raise revision_error("INVALID_RUN_ID", {"run_id": run_id}) from error
        return await self._workspace.finalize_run(validated.value)
