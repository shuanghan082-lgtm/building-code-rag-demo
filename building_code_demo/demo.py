"""Run the local demo, build optional vector index, and reproduce offline evaluation."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from .core import SOURCE_URL, extract_clauses
from .evaluation import evaluate, load_cases
from .prepare import fetch_verified
from .scan_catalog import FULL_SCAN_SHA256, FULL_SCAN_URL, ScanCatalog
from .service import DemoService, KNOWN_EXCERPT_SHA256
from .vector import OpenAIEmbeddingProvider, build_index


def _add_source(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--pdf", required=True, type=Path, help="本地政府节选 PDF")


def _add_mode(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--mode", choices=("lexical", "vector"), default="lexical")
    parser.add_argument("--index", type=Path, default=Path("data/excerpt.vector.json"))


def main() -> None:
    parser = argparse.ArgumentParser(description="建筑规范检索与模型导读演示")
    commands = parser.add_subparsers(dest="command", required=True)

    prepare = commands.add_parser("prepare", help="下载并验证政府 PDF 到本地忽略目录")
    prepare.add_argument("--source", choices=("excerpt", "full"), default="excerpt")
    prepare.add_argument("--out", type=Path, help="本地输出路径；默认 data/ 中的对应 PDF")

    retrieve = commands.add_parser("search", help="检索带出处的候选条文")
    _add_source(retrieve)
    _add_mode(retrieve)
    retrieve.add_argument("--query", required=True)
    retrieve.add_argument("--top-k", type=int, default=3)

    answer = commands.add_parser("answer", help="可选模型导读，始终需要原页核对")
    _add_source(answer)
    _add_mode(answer)
    answer.add_argument("--query", required=True)
    answer.add_argument("--top-k", type=int, default=3)

    scan = commands.add_parser("scan-search", help="仅定位完整扫描版原页，不输出 OCR 条文答案")
    scan.add_argument("--ocr", required=True, type=Path)
    scan.add_argument("--query", required=True)
    scan.add_argument("--top-k", type=int, default=3)

    index = commands.add_parser("index", help="用所配置的嵌入模型创建本地向量索引")
    _add_source(index)
    index.add_argument("--out", type=Path, default=Path("data/excerpt.vector.json"))

    eval_command = commands.add_parser("eval", help="复现离线字词检索评测")
    _add_source(eval_command)
    eval_command.add_argument("--cases", type=Path, default=Path("eval_cases.json"))
    eval_command.add_argument("--top-k", type=int, default=3)
    eval_command.add_argument("--out", type=Path, default=Path("data/eval_report.json"))

    serve = commands.add_parser("serve", help="启动本地浏览器界面")
    _add_source(serve)
    _add_mode(serve)
    serve.add_argument("--ocr-catalog", type=Path, help="可选：完整扫描版待核验 OCR JSON")
    serve.add_argument("--port", type=int, default=8765)

    args = parser.parse_args()
    if args.command == "prepare":
        url, digest, default_out = (
            (FULL_SCAN_URL, FULL_SCAN_SHA256, Path("data/full_standard.pdf"))
            if args.source == "full" else
            (SOURCE_URL, KNOWN_EXCERPT_SHA256, Path("data/official_excerpt.pdf"))
        )
        output = args.out or default_out
        status = fetch_verified(output, url, digest)
        print(f"{status}：{output}；SHA-256 已核对。文件只保存在本地，勿提交到公开仓库。")
        return
    if args.command == "scan-search":
        catalog = ScanCatalog.load(args.ocr)
        for hit in catalog.search(args.query, args.top_k):
            row = catalog.hit_dict(hit)
            print(f"扫描版 PDF 第 {row['pdf_page']} 页｜候选编号：{', '.join(row['candidate_clause_numbers'])}")
            print(row["source_url"])
        print("仅供定位原页；OCR 正文未经核验，不能作为规范答案。")
        return
    if args.command == "index":
        service = DemoService.load(args.pdf)
        key = os.getenv("RAG_API_KEY") or os.getenv("OPENAI_API_KEY")
        model = os.getenv("RAG_EMBED_MODEL")
        if not key or not model:
            parser.error("index 需要 RAG_API_KEY（或 OPENAI_API_KEY）与 RAG_EMBED_MODEL")
        provider = OpenAIEmbeddingProvider(key, model, os.getenv("RAG_BASE_URL"))
        built = build_index(service.clauses, provider)
        built.save(args.out)
        print(f"本地索引已保存：{args.out}；{len(built.numbers)} 条节选候选；模型 {model}")
        print("索引来自文字型节选且未经逐条人工核验，不代表完整规范。")
        return

    if args.command == "eval":
        service = DemoService.load(args.pdf)
        cases, cases_sha256 = load_cases(args.cases)
        result = evaluate(service.clauses, cases, args.top_k)
        result.update({
            "cases_sha256": cases_sha256,
            "source_pdf_sha256": KNOWN_EXCERPT_SHA256,
            "source_url": SOURCE_URL,
            "retrieval_mode": "lexical",
        })
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"正例 {result['positive_count']} 题，Recall@{args.top_k}={result['positive_recall_at_k']:.1%}")
        print(f"无答案题 {result['negative_count']} 题，零命中率={result['negative_no_hit_rate']:.1%}")
        print(f"失败 {len(result['failures'])} 题；明细：{args.out}")
        for item in result["failures"]:
            print(f"  {item['id']} 预期 {item['expected']}，返回 {item['retrieved']}")
        print("这些是节选的离线检索指标，不能代表答案正确率或完整规范效果。")
        return

    service = DemoService.load(
        args.pdf, args.mode, args.index,
        args.ocr_catalog if args.command == "serve" else None,
    )
    if args.command == "serve":
        try:
            import uvicorn
        except ImportError as error:
            raise RuntimeError('请先安装 python -m pip install -e ".[web]"') from error
        from .webapp import create_app

        print(f"本地演示：http://127.0.0.1:{args.port}")
        uvicorn.run(create_app(service), host="127.0.0.1", port=args.port, log_level="warning")
        return
    if args.top_k < 1 or args.top_k > 5:
        parser.error("--top-k 必须在 1–5 之间")
    if args.command == "answer":
        hits, result = service.answer(args.query, args.top_k)
        print(f"状态：{result.status}；{result.answer}")
        print(f"原因：{result.reason}；引用条文：{', '.join(result.citations) or '无'}")
    else:
        hits = service.retrieve(args.query, args.top_k)
    if not hits:
        print("没有找到候选；请核对官方原页和规范现行状态。")
    for hit in hits:
        row = service.hit_dict(hit)
        print(f"条文 {row['clause']}｜PDF 页 {row['pdf_page_first']}–{row['pdf_page_last']}｜分数 {row['score']}")
        print(row["snippet"])
        print(row["source_url"])


if __name__ == "__main__":
    main()
