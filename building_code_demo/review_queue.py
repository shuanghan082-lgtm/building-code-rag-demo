"""Create a local, metadata-only review queue from unverified OCR output."""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path


FIELDNAMES = (
    "candidate_clause_number",
    "pdf_page",
    "recognized_in_passes",
    "number_check_needed",
    "source_sha256",
    "review_status",
    "page_checked",
    "number_checked",
    "body_checked",
    "numbers_units_checked",
    "table_or_page_break_checked",
    "review_note",
)


def build_rows(observations: dict) -> list[dict[str, str]]:
    if observations.get("status") != "unverified_ocr_observations":
        raise ValueError("输入必须是待核验 OCR 观察文件")
    digest = observations.get("source", {}).get("sha256")
    if not digest:
        raise ValueError("输入缺少原始 PDF SHA-256")
    rows = []
    for page in observations.get("pages", []):
        passes = page.get("passes", {})
        for number in page.get("candidate_clause_numbers", []):
            names = sorted(
                name for name, result in passes.items()
                if number in result.get("candidate_clause_numbers", [])
            )
            rows.append({
                "candidate_clause_number": str(number),
                "pdf_page": str(page["pdf_page"]),
                "recognized_in_passes": ";".join(names),
                "number_check_needed": "yes" if len(names) < len(passes) else "no",
                "source_sha256": str(digest),
                "review_status": "pending",
                "page_checked": "no",
                "number_checked": "no",
                "body_checked": "no",
                "numbers_units_checked": "no",
                "table_or_page_break_checked": "no",
                "review_note": "",
            })
    return sorted(rows, key=lambda row: (int(row["pdf_page"]), row["candidate_clause_number"]))


def main() -> None:
    parser = argparse.ArgumentParser(description="为扫描版 OCR 生成本地逐条人工核验清单")
    parser.add_argument("--ocr", required=True, type=Path, help="由 ocr_import 生成的本地 JSON")
    parser.add_argument("--out", type=Path, default=Path("data/review_queue.csv"))
    args = parser.parse_args()
    observations = json.loads(args.ocr.read_text(encoding="utf-8"))
    rows = build_rows(observations)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDNAMES)
        writer.writeheader()
        writer.writerows(rows)
    print(f"已生成 {len(rows)} 条待核验候选记录：{args.out}（不代表真实条文数）")


if __name__ == "__main__":
    main()
