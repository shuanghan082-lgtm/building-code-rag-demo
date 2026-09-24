"""Keep OCR observations from a scanned PDF for human source verification.

This deliberately does not turn OCR text into a searchable or verified corpus.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re

import pymupdf as fitz


PASSES = (
    ("raw_2x", 2.0, None),
    ("threshold_140_3x", 3.0, 140),
    ("raw_3x", 3.0, None),
)
CLAUSE_START = re.compile(r"^\s*(\d+(?:\.\d+){2,3})(?![\d.])")


def page_selection(specification: str | None, page_count: int) -> list[int]:
    """Return one-based PDF page numbers, rejecting out-of-range selections."""
    if specification is None:
        return list(range(1, page_count + 1))
    try:
        selected = sorted({int(part.strip()) for part in specification.split(",")})
    except ValueError as error:
        raise ValueError("--pages 应为逗号分隔的 PDF 页码，例如 12,13,14") from error
    if not selected or selected[0] < 1 or selected[-1] > page_count:
        raise ValueError(f"--pages 页码必须在 1–{page_count} 之间")
    return selected


def _horizontal(box: list[list[float]]) -> bool:
    """Discard diagonal watermark candidates while retaining normal text."""
    dx = box[1][0] - box[0][0]
    dy = box[1][1] - box[0][1]
    return dx > 0 and abs(dy) <= dx * 0.20


def _recognize(page: fitz.Page, engine: object, scale: float, threshold: int | None) -> dict:
    import numpy as np

    pix = page.get_pixmap(matrix=fitz.Matrix(scale, scale), alpha=False)
    image = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, 3)
    if threshold is not None:
        gray = image.mean(axis=2)
        image = np.repeat(
            np.where(gray < threshold, 0, 255).astype(np.uint8)[:, :, None],
            3,
            axis=2,
        )
    result = engine(image)
    rows = []
    dropped_slanted = 0
    boxes = result.boxes if result.boxes is not None else []
    texts = result.txts if result.txts is not None else []
    scores = result.scores if result.scores is not None else []
    for box, value, score in zip(boxes, texts, scores):
        corners = [[round(float(x), 2), round(float(y), 2)] for x, y in box]
        if not _horizontal(corners):
            dropped_slanted += 1
            continue
        rows.append({"box": corners, "text": str(value), "score": round(float(score), 4)})
    rows.sort(key=lambda row: (min(p[1] for p in row["box"]), min(p[0] for p in row["box"])))
    numbers = sorted({match.group(1) for row in rows if (match := CLAUSE_START.match(row["text"]))})
    return {"rows": rows, "candidate_clause_numbers": numbers, "dropped_slanted": dropped_slanted}


def import_pdf(pdf_path: Path, selected_pages: str | None = None, source_url: str | None = None) -> dict:
    try:
        from rapidocr import RapidOCR
    except ImportError as error:
        raise RuntimeError('缺少 OCR 依赖；先运行 python -m pip install -e ".[ocr]"') from error

    if not pdf_path.is_file():
        raise FileNotFoundError(pdf_path)
    digest = hashlib.sha256(pdf_path.read_bytes()).hexdigest()
    engine = RapidOCR()
    pages = []
    with fitz.open(pdf_path) as document:
        chosen = page_selection(selected_pages, len(document))
        for page_number in chosen:
            page = document[page_number - 1]
            observations = {}
            for name, scale, threshold in PASSES:
                observations[name] = _recognize(page, engine, scale, threshold)
            candidates = sorted({number for item in observations.values() for number in item["candidate_clause_numbers"]})
            pages.append({
                "pdf_page": page_number,
                "candidate_clause_numbers": candidates,
                "passes": observations,
            })
            print(f"PDF 第 {page_number}/{len(document)} 页：候选条文号 {len(candidates)} 个", flush=True)
        total_pages = len(document)
    return {
        "schema_version": 1,
        "status": "unverified_ocr_observations",
        "warning": "OCR 文字与条文号均未经逐条人工核对；不能据此生成规范答案或合规结论。",
        "source": {"filename": pdf_path.name, "sha256": digest, "pdf_pages": total_pages, "url": source_url},
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "pass_settings": [
            {"name": name, "render_scale": scale, "gray_threshold": threshold}
            for name, scale, threshold in PASSES
        ],
        "processed_pages": chosen,
        "pages": pages,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="扫描版规范 OCR 观察导入（不进入检索语料）")
    parser.add_argument("--pdf", required=True, type=Path, help="本地扫描版 PDF 路径")
    parser.add_argument("--out", type=Path, default=Path("data/full_standard.ocr.json"))
    parser.add_argument("--pages", help="仅处理指定 PDF 页码，如 12,13,14；默认全部页")
    parser.add_argument("--source-url", help="该 PDF 的公开来源网址，用于人工核验溯源")
    args = parser.parse_args()
    observations = import_pdf(args.pdf, args.pages, args.source_url)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(observations, ensure_ascii=False, indent=2), encoding="utf-8")
    unique = {number for page in observations["pages"] for number in page["candidate_clause_numbers"]}
    print(f"已保存待核验记录：{args.out}；候选条文号 {len(unique)} 个（非验证后的覆盖率）")


if __name__ == "__main__":
    main()
