"""A single, traceable entry point for search and optional draft generation."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import os
from pathlib import Path
import re

from .answer import AnswerResult, OpenAIChatProvider, draft_answer
from .core import Clause, Hit, SOURCE_URL, extract_clauses, search
from .scan_catalog import ScanCatalog
from .vector import OpenAIEmbeddingProvider, VectorIndex, vector_search


KNOWN_EXCERPT_SHA256 = "eac0b134a46dae3b0054d85352a17a7bb54fb54213b6a9522784d4bd41318713"


@dataclass
class DemoService:
    clauses: list[Clause]
    selected_pages: list[int]
    pdf_sha256: str
    mode: str
    vector_index: VectorIndex | None = None
    embedding_provider: OpenAIEmbeddingProvider | None = None
    chat_provider: OpenAIChatProvider | None = None
    scan_catalog: ScanCatalog | None = None

    @classmethod
    def load(
        cls, pdf: Path, mode: str = "lexical", index_path: Path | None = None,
        scan_path: Path | None = None,
    ) -> "DemoService":
        digest = hashlib.sha256(pdf.read_bytes()).hexdigest()
        if digest != KNOWN_EXCERPT_SHA256:
            raise ValueError(
                "此演示只接受已核对 SHA-256 的政府节选 PDF；"
                "其他版本需要先独立核查来源、页码和解析结果。"
            )
        clauses, pages = extract_clauses(pdf)
        scan_catalog = ScanCatalog.load(scan_path) if scan_path is not None else None
        if mode == "lexical":
            return cls(clauses, pages, digest, mode, chat_provider=_chat_from_env(), scan_catalog=scan_catalog)
        if mode != "vector":
            raise ValueError("检索模式只能是 lexical 或 vector")
        key = os.getenv("RAG_API_KEY") or os.getenv("OPENAI_API_KEY")
        model = os.getenv("RAG_EMBED_MODEL")
        if not key or not model or index_path is None:
            raise ValueError("向量模式需要 RAG_API_KEY、RAG_EMBED_MODEL 和 --index")
        provider = OpenAIEmbeddingProvider(key, model, os.getenv("RAG_BASE_URL"))
        index = VectorIndex.load(index_path, clauses, model)
        return cls(clauses, pages, digest, mode, index, provider, _chat_from_env(), scan_catalog)

    def retrieve(self, query: str, top_k: int = 3) -> list[Hit]:
        if self.mode == "vector":
            assert self.vector_index is not None and self.embedding_provider is not None
            return vector_search(self.clauses, self.vector_index, query, self.embedding_provider, top_k)
        return search(self.clauses, query, top_k)

    def answer(self, query: str, top_k: int = 3) -> tuple[list[Hit], AnswerResult]:
        hits = self.retrieve(query, top_k)
        return hits, draft_answer(query, hits, self.chat_provider)

    def hit_dict(self, hit: Hit) -> dict:
        clause = hit.clause
        warnings = []
        if clause.last_pdf_page != clause.first_pdf_page:
            warnings.append("条文跨 PDF 页面，需核对续文")
        if re.search(r"表\s*\d+\.\d+\.\d+", clause.text):
            warnings.append("涉及表格，提取文本可能丢失行列关系")
        if re.search(r"\d+\.O\s*(?:mm|m)", clause.text, re.IGNORECASE):
            warnings.append("数值疑有字体映射错误，需核对原图")
        return {
            "clause": clause.number,
            "pdf_page_first": clause.first_pdf_page,
            "pdf_page_last": clause.last_pdf_page,
            "score": hit.score,
            "snippet": clause.text[:500] + ("…" if len(clause.text) > 500 else ""),
            "source_url": f"{SOURCE_URL}#page={clause.first_pdf_page}",
            "source_status": "government_excerpt_text_layer_not_fully_manually_verified",
            "warnings": warnings,
        }


def _chat_from_env() -> OpenAIChatProvider | None:
    key = os.getenv("RAG_API_KEY") or os.getenv("OPENAI_API_KEY")
    model = os.getenv("RAG_CHAT_MODEL")
    if not key or not model:
        return None
    return OpenAIChatProvider(key, model, os.getenv("RAG_BASE_URL"))
