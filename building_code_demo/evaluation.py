"""Offline retrieval evaluation; never treats retrieval as answer correctness."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from .core import Clause, Hit, search


def evaluate(clauses: list[Clause], cases: list[dict], top_k: int = 3) -> dict:
    if top_k < 1:
        raise ValueError("top_k 必须为正数")
    available = {clause.number for clause in clauses}
    seen_ids = set()
    details = []
    for case in cases:
        case_id = case["id"]
        if case_id in seen_ids:
            raise ValueError(f"评测题 ID 重复：{case_id}")
        seen_ids.add(case_id)
        expected = set(case["expected"])
        if not expected.issubset(available):
            raise ValueError(f"评测标注不在节选语料：{case_id}")
        hits: list[Hit] = search(clauses, case["question"], top_k)
        retrieved = [hit.clause.number for hit in hits]
        rank = next((i + 1 for i, number in enumerate(retrieved) if number in expected), None)
        details.append({
            "id": case_id,
            "question": case["question"],
            "expected": sorted(expected),
            "retrieved": retrieved,
            "first_expected_rank": rank,
            "pass": (rank is not None) if expected else (not retrieved),
        })
    positive = [item for item in details if item["expected"]]
    negative = [item for item in details if not item["expected"]]
    return {
        "scope": "five-page excerpt only; lexical retrieval, not legal answer evaluation",
        "top_k": top_k,
        "positive_count": len(positive),
        "negative_count": len(negative),
        "positive_recall_at_k": round(sum(item["pass"] for item in positive) / len(positive), 4) if positive else None,
        "negative_no_hit_rate": round(sum(item["pass"] for item in negative) / len(negative), 4) if negative else None,
        "reciprocal_rank_mean": round(sum(1 / item["first_expected_rank"] for item in positive if item["first_expected_rank"]) / len(positive), 4) if positive else None,
        "failures": [item for item in details if not item["pass"]],
        "details": details,
    }


def load_cases(path: Path) -> tuple[list[dict], str]:
    content = path.read_bytes()
    payload = json.loads(content)
    cases = payload["cases"]
    if not isinstance(cases, list):
        raise ValueError("评测集格式错误")
    return cases, hashlib.sha256(content).hexdigest()
