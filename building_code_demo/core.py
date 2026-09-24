"""Extract numbered clauses and run a small, dependency-light retrieval baseline.

This module deliberately does not call an LLM or claim compliance decisions.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from math import log
from pathlib import Path
import re

import pymupdf as fitz


STANDARD_CODE = "GB 55031-2022"
STANDARD_TITLE = "民用建筑通用规范"
SOURCE_URL = (
    "https://ghzrzyw.beijing.gov.cn/biaozhunguanli/bzzl/202209/"
    "P020220929592779805981.pdf"
)
SOURCE_DESCRIPTION = "北京市规划和自然资源委员会公开的标准摘录；仅包含所选条文，非规范全文"

_CLAUSE_START = re.compile(r"(?m)^\s*(\d+(?:\.\d+){2,3})\s*")
_CLAUSE_IN_QUERY = re.compile(r"(?<!\d)(\d+(?:\.\d+){2,3})(?!\d)")
_HEADER_END = re.compile(r"2023\s*年\s*03\s*月\s*01\s*日\s*实\s*施")


@dataclass(frozen=True)
class Clause:
    number: str
    text: str
    first_pdf_page: int
    last_pdf_page: int


@dataclass(frozen=True)
class Hit:
    clause: Clause
    score: float


def _clean_text(raw: str) -> str:
    """Collapse PDF line wraps while keeping subitems legible."""
    lines = [line.strip() for line in raw.splitlines() if line.strip()]
    joined = " ".join(lines)
    return re.sub(r"\s+", " ", joined).strip()


def extract_clauses(pdf_path: str | Path) -> tuple[list[Clause], list[int]]:
    """Extract only pages explicitly headed as GB 55031-2022.

    The published sample is a multi-standard *excerpt*. Other standards in the
    same PDF are excluded, and no missing clause is inferred from numbering.
    """
    path = Path(pdf_path)
    if not path.is_file():
        raise FileNotFoundError(f"PDF 不存在：{path}")

    clauses: list[Clause] = []
    selected_pages: list[int] = []
    current_number: str | None = None
    current_parts: list[str] = []
    first_page = last_page = 0

    def finish() -> None:
        nonlocal current_number, current_parts
        if current_number is not None:
            text = _clean_text("\n".join(current_parts))
            if text:
                clauses.append(Clause(current_number, text, first_page, last_page))
        current_number = None
        current_parts = []

    with fitz.open(path) as document:
        for page_index, page in enumerate(document):
            raw = page.get_text()
            if STANDARD_CODE not in raw or f"《{STANDARD_TITLE}》" not in raw:
                continue
            match_header = _HEADER_END.search(raw)
            if not match_header:
                continue  # A contents page may mention this standard without containing clauses.
            pdf_page = page_index + 1
            selected_pages.append(pdf_page)
            body = raw[match_header.end() :]
            matches = list(_CLAUSE_START.finditer(body))

            if not matches:
                if current_number is not None:
                    current_parts.append(body)
                    last_page = pdf_page
                continue

            prefix = body[: matches[0].start()]
            if current_number is not None and prefix.strip():
                current_parts.append(prefix)
                last_page = pdf_page

            for position, marker in enumerate(matches):
                finish()
                current_number = marker.group(1)
                first_page = last_page = pdf_page
                end = matches[position + 1].start() if position + 1 < len(matches) else len(body)
                current_parts = [body[marker.end() : end]]

    finish()
    if not selected_pages or not clauses:
        raise ValueError(
            "没有提取到可检索条文：请使用含可选中文文字的 GB 55031-2022 PDF；"
            "图像扫描版需要另行 OCR，当前原型不支持。"
        )
    return clauses, selected_pages


def _tokens(text: str) -> list[str]:
    """Character 2/3-grams suit Chinese short queries without a tokenizer."""
    compact = re.sub(r"\s+", "", text.casefold())
    compact = re.sub(r"[^\u4e00-\u9fffa-z0-9.%]+", "", compact)
    return [compact[i : i + n] for n in (2, 3) for i in range(max(0, len(compact) - n + 1))]


def search(clauses: list[Clause], query: str, limit: int = 3) -> list[Hit]:
    """BM25-style lexical baseline; returned hits are candidates, not answers."""
    if not query.strip() or limit < 1:
        return []
    requested_clause = _CLAUSE_IN_QUERY.search(query)
    if requested_clause and not any(c.number == requested_clause.group(1) for c in clauses):
        return []  # An absent clause must not be replaced with a nearby number.

    documents = [Counter(_tokens(c.text)) for c in clauses]
    doc_lengths = [sum(counts.values()) for counts in documents]
    average_length = sum(doc_lengths) / max(len(doc_lengths), 1)
    query_tokens = set(_tokens(query))
    document_frequency = Counter(token for counts in documents for token in counts)
    hits: list[Hit] = []
    for clause, counts, length in zip(clauses, documents, doc_lengths):
        score = 0.0
        for token in query_tokens:
            frequency = counts[token]
            if not frequency:
                continue
            inverse_frequency = log(
                1 + (len(clauses) - document_frequency[token] + 0.5)
                / (document_frequency[token] + 0.5)
            )
            score += inverse_frequency * frequency * 2.2 / (
                frequency + 1.2 * (0.25 + 0.75 * length / average_length)
            )
        if requested_clause and clause.number == requested_clause.group(1):
            score += 100.0
        if score > 0:
            hits.append(Hit(clause, round(score, 4)))
    return sorted(hits, key=lambda hit: (-hit.score, hit.clause.number))[:limit]
