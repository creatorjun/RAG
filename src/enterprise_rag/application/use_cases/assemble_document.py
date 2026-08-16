from __future__ import annotations

import re

from enterprise_rag.application.dto.evidence import EvidenceBundleDto
from enterprise_rag.application.dto.tasks import (
    TaskOutputDto,
    TaskPacketDto,
    TaskPlanDto,
    TaskValidationReportDto,
)
from enterprise_rag.application.use_cases.polish_document import PolishDocument
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
        ):
            raise revision_error("DOCUMENT_ASSEMBLY_FAILED")
        path_by_evidence = {
            item.evidence_id: item.relative_path for item in evidence.items
        }
        parts = [f"# {self._clean_heading(title)}"]
        grouped_tasks: dict[str, list[TaskPacketDto]] = {}
        task_title_by_key: dict[str, str] = {}
        for task in plan.tasks:
            task_title = self._clean_heading(task.title)
            key = self._heading_key(task_title)
            grouped_tasks.setdefault(key, []).append(task)
            task_title_by_key.setdefault(key, task_title)
        for task_key, tasks in grouped_tasks.items():
            parts.append(f"## {task_title_by_key[task_key]}")
            sections_by_heading: dict[str, list[str]] = {}
            heading_by_key: dict[str, str] = {}
            for task in tasks:
                output = output_by_task[task.task_id]
                section_by_key = {
                    section.section_key: section for section in output.sections
                }
                ordered_keys = [
                    section_key
                    for section_key in task.required_sections
                    if section_key in section_by_key
                ]
                ordered_keys.extend(
                    section.section_key
                    for section in output.sections
                    if section.section_key not in ordered_keys
                )
                for section_key in ordered_keys:
                    section = section_by_key[section_key]
                    heading = self._clean_heading(section.heading)
                    heading_key = self._heading_key(heading)
                    rendered = _EVIDENCE_MARKER.sub(
                        lambda match: self._citation(
                            match.group(0), match.group(1), path_by_evidence
                        ),
                        section.markdown.strip(),
                    )
                    heading_by_key.setdefault(heading_key, heading)
                    sections_by_heading.setdefault(heading_key, []).append(rendered)
            for heading_key, rendered_sections in sections_by_heading.items():
                parts.append(
                    f"### {heading_by_key[heading_key]}\n\n"
                    + "\n\n".join(rendered_sections)
                )
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
        return PolishDocument().execute("\n\n".join(parts))

    @staticmethod
    def _citation(marker: str, evidence_id: str, paths: dict[str, str]) -> str:
        path = paths.get(evidence_id)
        if path is None:
            return marker
        return f"[source:{path}]"

    @staticmethod
    def _clean_heading(value: str) -> str:
        cleaned = re.sub(r"^\s{0,3}#{1,6}\s*", "", value).strip()
        return cleaned or value.strip() or "섹션"

    @classmethod
    def _heading_key(cls, value: str) -> str:
        return " ".join(cls._clean_heading(value).casefold().split())
