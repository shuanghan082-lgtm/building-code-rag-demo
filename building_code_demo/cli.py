"""Run the first, retrieval-only vertical slice."""

from __future__ import annotations

import argparse
from pathlib import Path

from .core import (
    SOURCE_DESCRIPTION,
    SOURCE_URL,
    STANDARD_CODE,
    STANDARD_TITLE,
    extract_clauses,
    search,
)


def main() -> None:
    parser = argparse.ArgumentParser(description="建筑规范条文检索基线（仅检索，不生成合规结论）")
    parser.add_argument("--pdf", required=True, type=Path, help="自行从政府网站取得的可选中文字 PDF")
    parser.add_argument("--query", required=True, help="检索问题或条文号")
    parser.add_argument("--top-k", type=int, default=3, help="最多显示几条候选条文")
    args = parser.parse_args()

    clauses, pages = extract_clauses(args.pdf)
    hits = search(clauses, args.query, args.top_k)
    print(f"资料：{STANDARD_TITLE} {STANDARD_CODE}｜{SOURCE_DESCRIPTION}")
    print(f"已识别 PDF 页：{pages[0]}–{pages[-1]}，条文：{len(clauses)}；这不能证明全文覆盖。")
    print(f"官方来源：{SOURCE_URL}")
    print("当前功能：字词检索基线；未接入 LLM 或语义向量检索。候选条文不能代替专业核验。")
    if not hits:
        print("未找到对应条文。该 PDF 可能只含节选；请核对官方原文及适用版本。")
        return
    for index, hit in enumerate(hits, 1):
        page_label = str(hit.clause.first_pdf_page)
        if hit.clause.last_pdf_page != hit.clause.first_pdf_page:
            page_label += f"–{hit.clause.last_pdf_page}"
        print(f"\n{index}. 条文 {hit.clause.number}｜PDF 页 {page_label}｜检索分数 {hit.score:.2f}")
        print(hit.clause.text[:320] + ("…" if len(hit.clause.text) > 320 else ""))


if __name__ == "__main__":
    main()
