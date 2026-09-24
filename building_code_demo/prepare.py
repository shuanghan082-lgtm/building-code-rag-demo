"""Fetch the public excerpt into ignored local data, verifying exact source bytes."""

from __future__ import annotations

import hashlib
from pathlib import Path
from urllib.request import Request, urlopen

from .core import SOURCE_URL
from .service import KNOWN_EXCERPT_SHA256


MAX_PDF_BYTES = 20 * 1024 * 1024


def fetch_verified(
    output: Path,
    url: str = SOURCE_URL,
    expected_sha256: str = KNOWN_EXCERPT_SHA256,
    opener=urlopen,
) -> str:
    """Never replace an existing file unless it is already the pinned PDF."""
    if output.exists():
        digest = hashlib.sha256(output.read_bytes()).hexdigest()
        if digest == expected_sha256:
            return "already_verified"
        raise ValueError(f"目标文件已存在但 SHA-256 不符：{output}")
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_suffix(output.suffix + ".download")
    digest = hashlib.sha256()
    total = 0
    try:
        request = Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with opener(request, timeout=30) as response, temporary.open("wb") as destination:
            while True:
                block = response.read(1024 * 1024)
                if not block:
                    break
                total += len(block)
                if total > MAX_PDF_BYTES:
                    raise ValueError("来源文件超过预期大小，已中止下载")
                digest.update(block)
                destination.write(block)
        if digest.hexdigest() != expected_sha256:
            raise ValueError("来源 PDF 指纹与核验记录不一致；请重新检查政府页面，勿直接运行")
        if temporary.read_bytes()[:4] != b"%PDF":
            raise ValueError("下载结果不是 PDF")
        temporary.replace(output)
    finally:
        temporary.unlink(missing_ok=True)
    return "downloaded_verified"
