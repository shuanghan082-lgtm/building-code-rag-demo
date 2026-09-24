"""Local-only FastAPI interface for search and optional model-assisted reading."""

from __future__ import annotations

from importlib.resources import files

from .service import DemoService

try:
    from fastapi import FastAPI, HTTPException
    from fastapi.responses import HTMLResponse
    from pydantic import BaseModel, Field
except ImportError as error:
    raise RuntimeError('请先安装 python -m pip install -e ".[web]"') from error


class QueryRequest(BaseModel):
    question: str = Field(min_length=1, max_length=300)
    top_k: int = Field(default=3, ge=1, le=5)


def create_app(service: DemoService):
    app = FastAPI(title="建筑规范条文检索演示", docs_url=None, redoc_url=None)

    @app.get("/", response_class=HTMLResponse)
    def homepage():
        return files("building_code_demo").joinpath("static/index.html").read_text(encoding="utf-8")

    @app.get("/api/info")
    def info():
        return {
            "standard": "GB 55031-2022 民用建筑通用规范",
            "scope": "政府公开 PDF 的 5 页节选，不是规范全文",
            "pdf_pages": service.selected_pages,
            "clauses": len(service.clauses),
            "retrieval_mode": service.mode,
            "chat_configured": service.chat_provider is not None,
            "scan_locator_available": service.scan_catalog is not None,
            "source_sha256": service.pdf_sha256,
            "warning": "提取文字未经逐条人工核验，必须打开原 PDF 核对；不作合规结论。",
        }

    @app.post("/api/search")
    def search_query(request: QueryRequest):
        try:
            hits = service.retrieve(request.question, request.top_k)
        except Exception as error:
            raise HTTPException(status_code=502, detail="检索服务暂不可用，请检查本地模型配置") from error
        return {"hits": [service.hit_dict(hit) for hit in hits], "mode": service.mode}

    @app.post("/api/answer")
    def answer_query(request: QueryRequest):
        if service.chat_provider is None:
            raise HTTPException(status_code=409, detail="尚未配置聊天模型；可先使用离线检索")
        try:
            hits, answer = service.answer(request.question, request.top_k)
        except Exception as error:
            raise HTTPException(status_code=502, detail="模型调用失败，请检查配置或稍后重试") from error
        return {
            "hits": [service.hit_dict(hit) for hit in hits],
            "answer": {
                "status": answer.status,
                "text": answer.answer,
                "citations": answer.citations,
                "reason": answer.reason,
            },
        }

    @app.post("/api/scan")
    def scan_query(request: QueryRequest):
        if service.scan_catalog is None:
            raise HTTPException(status_code=409, detail="未加载完整扫描版 OCR 观察文件")
        hits = service.scan_catalog.search(request.question, request.top_k)
        return {
            "hits": [service.scan_catalog.hit_dict(hit) for hit in hits],
            "mode": "unverified_scan_page_locator",
        }

    return app
