# src/enterprise_rag/infrastructure/tokenization/conservative_utf8.py
from __future__ import annotations


class ConservativeUtf8TokenCounter:
    @property
    def identifier(self) -> str:
        return "conservative-utf8-bytes-v1"

    def count(self, text: str) -> int:
        return len(text.encode("utf-8"))

    def prefix_end(self, text: str, start: int, maximum_tokens: int) -> int:
        if not 0 <= start <= len(text):
            raise ValueError("start is outside text")
        if maximum_tokens < 0:
            raise ValueError("maximum tokens must be non-negative")
        consumed = 0
        end = start
        while end < len(text):
            width = len(text[end].encode("utf-8"))
            if consumed + width > maximum_tokens:
                break
            consumed += width
            end += 1
        return end

    def suffix_start(self, text: str, end: int, maximum_tokens: int) -> int:
        if not 0 <= end <= len(text):
            raise ValueError("end is outside text")
        if maximum_tokens < 0:
            raise ValueError("maximum tokens must be non-negative")
        consumed = 0
        start = end
        while start > 0:
            width = len(text[start - 1].encode("utf-8"))
            if consumed + width > maximum_tokens:
                break
            consumed += width
            start -= 1
        return start
