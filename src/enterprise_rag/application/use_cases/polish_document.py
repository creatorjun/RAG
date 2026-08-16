from __future__ import annotations

import re
import unicodedata

_SOURCE_CITATION = re.compile(r"\[source:([^\]\r\n]+)\]")
_INTERNAL_EVIDENCE = re.compile(r"\[evidence:[^\]\r\n]+\]")
_INTERNAL_CLAIM = re.compile(r"\[claim:[^\]\r\n]+\]")
_ASSIGNED_SECRET = re.compile(
    r"(?i)(?P<key>\b[A-Z0-9_.-]*(?:TOKEN|PASSWORD|PASSWD|SECRET|"
    r"API[_-]?KEY|PRIVATE[_-]?KEY)[A-Z0-9_.-]*\b)"
    r"(?P<separator>\s*[:=]\s*)(?P<quote>['\"]?)(?P<value>[^\s'\"`]+)(?P=quote)"
)
_JSON_SECRET = re.compile(
    r"(?i)(?P<prefix>['\"][^'\"]*(?:TOKEN|PASSWORD|PASSWD|SECRET|"
    r"API[_-]?KEY|PRIVATE[_-]?KEY)[^'\"]*['\"]\s*:\s*)"
    r"(?P<quote>['\"])(?P<value>[^'\"]+)(?P=quote)"
)


class PolishDocument:
    """Apply safe, deterministic publication cleanup without acting as a gate."""

    def execute(self, markdown: str) -> str:
        value = unicodedata.normalize("NFC", markdown.replace("\r\n", "\n").replace("\r", "\n"))
        value = _INTERNAL_EVIDENCE.sub("", value)
        value = _INTERNAL_CLAIM.sub("", value)
        value = self._redact_secrets(value)
        value = self._deduplicate_prose_blocks(value)
        value = re.sub(r"[ \t]+\n", "\n", value)
        value = re.sub(r"\n{3,}", "\n\n", value)
        return value.strip() + "\n"

    @staticmethod
    def _redact_secrets(markdown: str) -> str:
        replacement = "[민감정보 제거]"
        value = _JSON_SECRET.sub(
            lambda match: f"{match.group('prefix')}{match.group('quote')}{replacement}"
            f"{match.group('quote')}",
            markdown,
        )
        return _ASSIGNED_SECRET.sub(
            lambda match: f"{match.group('key')}{match.group('separator')}"
            f"{match.group('quote')}{replacement}{match.group('quote')}",
            value,
        )

    @classmethod
    def _deduplicate_prose_blocks(cls, markdown: str) -> str:
        blocks = re.split(r"\n{2,}", markdown)
        rendered: list[str] = []
        index_by_fingerprint: dict[str, int] = {}
        for block in blocks:
            stripped = block.strip()
            fingerprint = cls._prose_fingerprint(stripped)
            if fingerprint is None or fingerprint not in index_by_fingerprint:
                if fingerprint is not None:
                    index_by_fingerprint[fingerprint] = len(rendered)
                rendered.append(stripped)
                continue
            existing_index = index_by_fingerprint[fingerprint]
            existing = rendered[existing_index]
            known_sources = set(_SOURCE_CITATION.findall(existing))
            additional = [
                source
                for source in _SOURCE_CITATION.findall(stripped)
                if source not in known_sources
            ]
            if additional:
                citations = " ".join(f"[source:{source}]" for source in additional)
                rendered[existing_index] = (
                    existing.rstrip() + " " + citations
                )
        return "\n\n".join(block for block in rendered if block)

    @staticmethod
    def _prose_fingerprint(block: str) -> str | None:
        if len(block) < 60:
            return None
        lines = block.splitlines()
        structural_prefixes = ("#", "```", "~~~", "|", ">", "- ", "* ", "+ ")
        if any(line.lstrip().startswith(structural_prefixes) for line in lines):
            return None
        without_sources = _SOURCE_CITATION.sub("", block)
        return " ".join(without_sources.casefold().split())
