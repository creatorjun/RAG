from __future__ import annotations

import re

from enterprise_rag.application.dto.evidence import EvidenceBundleDto
from enterprise_rag.application.dto.tasks import (
    TaskOutputDto,
    TaskPlanDto,
    TaskValidationReportDto,
)
from enterprise_rag.domain.errors import revision_error

_EVIDENCE_MARKER = re.compile(r"\[evidence:(evidence:sha256:[0-9a-f]{64})\]")


class AssembleDocument:
    def execute(
        self,
        title: str,
        plan: TaskPlanDto,
        evidence: EvidenceBundleDto,
        outputs: tuple[TaskOutputDto, ...],
        validations: tuple[TaskValidationReportDto, ...],
    ) -> str:
        if not title.strip():
            raise revision_error("DOCUMENT_ASSEMBLY_FAILED")
        output_by_task = {output.task_id: output for output in outputs}
        report_by_task = {report.task_id: report for report in validations}
        task_ids = {task.task_id for task in plan.tasks}
        if (
            len(output_by_task) != len(outputs)
            or len(report_by_task) != len(validations)
            or set(output_by_task) != task_ids
            or set(report_by_task) != task_ids
            or any(not report.valid for report in validations)
        ):
            raise revision_error("DOCUMENT_ASSEMBLY_FAILED")
        path_by_evidence = {
            item.evidence_id: item.relative_path for item in evidence.items
        }
        parts = [f"# {title.strip()}"]
        for task in plan.tasks:
            output = output_by_task[task.task_id]
            section_by_key = {
                section.section_key: section for section in output.sections
            }
            parts.append(f"## {task.title}")
            for section_key in task.required_sections:
                section = section_by_key.get(section_key)
                if section is None:
                    raise revision_error("DOCUMENT_ASSEMBLY_FAILED")
                rendered = _EVIDENCE_MARKER.sub(
                    lambda match: self._citation(match.group(1), path_by_evidence),
                    section.markdown.strip(),
                )
                if "[evidence:" in rendered or "[source:" not in rendered:
                    raise revision_error("DOCUMENT_ASSEMBLY_FAILED")
                parts.append(f"### {section.heading}\n\n{rendered}")
        included_evidence = {
            entry.evidence_id for entry in plan.coverage.evidence_coverage
        }
        source_paths = sorted(
            {
                item.relative_path
                for item in evidence.items
                if item.evidence_id in included_evidence
            }
        )
        inventory = "\n".join(f"- `{path}`" for path in source_paths)
        parts.append(f"## 원본 문서 목록\n\n{inventory}")
        return "\n\n".join(parts).rstrip() + "\n"

    @staticmethod
    def _citation(evidence_id: str, paths: dict[str, str]) -> str:
        path = paths.get(evidence_id)
        if path is None:
            raise revision_error("DOCUMENT_ASSEMBLY_FAILED")
        return f"[source:{path}]"
