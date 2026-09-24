"""Experimental page locator for the complete, unverified scanned PDF.

Only page numbers and candidate clause IDs are returned; OCR body stays local.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
from math import log
from pathlib import Path

from .core import _CLAUSE_IN_QUERY, _tokens


FULL_SCAN_SHA256 = "0c792fac5b2524f0326dcb750d89ed90c23cd2768f49dcbdfbd3679ca911bf8e"
FULL_SCAN_URL = "https://zjj.sm.gov.cn/xxgk/fgwj/jsbz/202209/P020220909629255603704.pdf"


@dataclass(frozen=True)
class ScanPage:
    pdf_page: int
    candidate_numbers: list[str]
    tokens: frozenset[str]


@dataclass(frozen=True)
class ScanHit:
    page: ScanPage
    score: float


class ScanCatalog:
    def __init__(self, pages: list[ScanPage]):
        self.pages = pages
        self.numbers = {number for page in pages for number in page.candidate_numbers}

    @classmethod
    def load(cls, path: Path) -> "ScanCatalog":
        payload = json.loads(path.read_text(encoding="utf-8"))
        if payload.get("status") != "unverified_ocr_observations":
            raise ValueError("扫描版定位只接受待核验 OCR 观察文件")
        source = payload.get("source", {})
        if source.get("sha256", "").lower() != FULL_SCAN_SHA256 or source.get("pdf_pages") != 24:
            raise ValueError("扫描版 PDF 指纹或页数不匹配，拒绝套用已有页码")
        pages = []
        for page in payload.get("pages", []):
            lines = {
                row.get("text", "")
                for result in page.get("passes", {}).values()
                for row in result.get("rows", [])
            }
            tokens = frozenset(_tokens(" ".join(sorted(lines))))
            numbers = sorted(page["candidate_clause_numbers"], key=lambda number: tuple(int(part) for part in number.split(".")))
            pages.append(ScanPage(int(page["pdf_page"]), numbers, tokens))
        if sorted(page.pdf_page for page in pages) != list(range(1, 25)):
            raise ValueError("扫描版 OCR 文件没有完整的 24 页观察结果")
        return cls(pages)

    def search(self, query: str, limit: int = 3) -> list[ScanHit]:
        if not query.strip() or limit < 1:
            return []
        requested = _CLAUSE_IN_QUERY.search(query)
        if requested and requested.group(1) not in self.numbers:
            return []
        terms = set(_tokens(query))
        document_frequency = {term: sum(term in page.tokens for page in self.pages) for term in terms}
        hits = []
        for page in self.pages:
            score = sum(log(1 + (len(self.pages) + 0.5) / (frequency + 0.5)) for term, frequency in document_frequency.items() if term in page.tokens)
            if requested and requested.group(1) in page.candidate_numbers:
                score += 100.0
            if score > 0:
                hits.append(ScanHit(page, round(score, 4)))
        return sorted(hits, key=lambda hit: (-hit.score, hit.page.pdf_page))[:limit]

    @staticmethod
    def hit_dict(hit: ScanHit) -> dict:
        return {
            "pdf_page": hit.page.pdf_page,
            "candidate_clause_numbers": hit.page.candidate_numbers,
            "score": hit.score,
            "source_url": f"{FULL_SCAN_URL}#page={hit.page.pdf_page}",
            "status": "unverified_ocr_page_locator_only",
            "warning": "按 OCR 文字近似匹配排序；正文未经核验，只用于定位原页，不能作为条文答案。",
        }
