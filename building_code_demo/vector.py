"""Optional exact cosine search over API embeddings, with local provenance checks."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from math import isfinite, sqrt
from pathlib import Path
from typing import Protocol

from .core import Clause, Hit


class EmbeddingProvider(Protocol):
    model: str

    def embed(self, texts: list[str]) -> list[list[float]]: ...


def corpus_fingerprint(clauses: list[Clause]) -> str:
    payload = [
        [clause.number, clause.text, clause.first_pdf_page, clause.last_pdf_page]
        for clause in clauses
    ]
    content = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def _unit(vector: list[float]) -> list[float]:
    if not vector or any(not isfinite(float(value)) for value in vector):
        raise ValueError("嵌入向量为空或含非有限数值")
    magnitude = sqrt(sum(float(value) ** 2 for value in vector))
    if not isfinite(magnitude) or magnitude <= 0:
        raise ValueError("向量不能全为零")
    return [float(value) / magnitude for value in vector]


@dataclass(frozen=True)
class VectorIndex:
    model: str
    corpus_sha256: str
    numbers: list[str]
    vectors: list[list[float]]

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({
            "schema_version": 1,
            "status": "local_derived_index_not_verified_standard",
            "model": self.model,
            "corpus_sha256": self.corpus_sha256,
            "numbers": self.numbers,
            "vectors": self.vectors,
        }, ensure_ascii=False), encoding="utf-8")

    @classmethod
    def load(cls, path: Path, clauses: list[Clause], model: str) -> "VectorIndex":
        payload = json.loads(path.read_text(encoding="utf-8"))
        if payload.get("schema_version") != 1 or payload.get("model") != model:
            raise ValueError("向量索引版本或模型不匹配，请重新构建")
        if payload.get("corpus_sha256") != corpus_fingerprint(clauses):
            raise ValueError("PDF 提取语料已变化，请重新构建向量索引")
        numbers = [clause.number for clause in clauses]
        if payload.get("numbers") != numbers or len(payload.get("vectors", [])) != len(numbers):
            raise ValueError("向量索引与条文顺序不一致，请重新构建")
        vectors = [_unit(vector) for vector in payload["vectors"]]
        if len({len(vector) for vector in vectors}) != 1:
            raise ValueError("向量索引维度不一致")
        return cls(model, payload["corpus_sha256"], numbers, vectors)


def build_index(clauses: list[Clause], provider: EmbeddingProvider, batch_size: int = 16) -> VectorIndex:
    if not clauses or batch_size < 1:
        raise ValueError("构建索引需要非空条文与正数批次")
    vectors = []
    for start in range(0, len(clauses), batch_size):
        batch = clauses[start:start + batch_size]
        texts = [f"{clause.number} {clause.text}" for clause in batch]
        returned = provider.embed(texts)
        if len(returned) != len(batch):
            raise ValueError("嵌入接口返回数量与请求数量不符")
        vectors.extend(_unit(vector) for vector in returned)
    if len({len(vector) for vector in vectors}) != 1:
        raise ValueError("嵌入接口返回向量维度不一致")
    return VectorIndex(provider.model, corpus_fingerprint(clauses), [c.number for c in clauses], vectors)


def vector_search(
    clauses: list[Clause], index: VectorIndex, query: str, provider: EmbeddingProvider, limit: int = 3,
) -> list[Hit]:
    if not query.strip() or limit < 1:
        return []
    if index.model != provider.model or index.corpus_sha256 != corpus_fingerprint(clauses):
        raise ValueError("向量模型或语料与当前索引不一致")
    from .core import _CLAUSE_IN_QUERY

    requested = _CLAUSE_IN_QUERY.search(query)
    if requested and not any(clause.number == requested.group(1) for clause in clauses):
        return []
    returned = provider.embed([query])
    if len(returned) != 1:
        raise ValueError("查询嵌入接口应返回一个向量")
    vector = _unit(returned[0])
    if len(vector) != len(index.vectors[0]):
        raise ValueError("查询向量维度与索引不一致")
    hits = []
    for clause, stored in zip(clauses, index.vectors):
        similarity = sum(a * b for a, b in zip(vector, stored))
        if requested and clause.number == requested.group(1):
            similarity += 2.0
        hits.append(Hit(clause, round(similarity, 5)))
    return sorted(hits, key=lambda item: (-item.score, item.clause.number))[:limit]


class OpenAIEmbeddingProvider:
    def __init__(self, api_key: str, model: str, base_url: str | None = None):
        if not api_key or not model:
            raise ValueError("向量模式需要 API 密钥和嵌入模型名称")
        try:
            from openai import OpenAI
        except ImportError as error:
            raise RuntimeError('请先安装 python -m pip install -e ".[llm]"') from error
        self.model = model
        self.client = OpenAI(api_key=api_key, base_url=base_url, timeout=30.0, max_retries=1)

    def embed(self, texts: list[str]) -> list[list[float]]:
        result = self.client.embeddings.create(model=self.model, input=texts)
        ordered = sorted(result.data, key=lambda item: item.index)
        return [list(item.embedding) for item in ordered]
