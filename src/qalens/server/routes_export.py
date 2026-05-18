"""Chat result export route for the QA Lens FastAPI server."""

from __future__ import annotations

import re
from typing import Any

from fastapi import APIRouter
from fastapi.responses import Response
from pydantic import BaseModel


class ChatExportRequest(BaseModel):
    question: str = ""
    answer: str = ""
    result: dict[str, Any] | None = None
    autoprint: bool = False


def make_export_router() -> APIRouter:
    """Return an APIRouter with chat result export endpoints."""
    router = APIRouter()

    @router.post("/api/export/chat-result", tags=["export"], include_in_schema=False)
    async def export_chat_result(body: ChatExportRequest) -> Response:
        """Render a chat Q&A result as a standalone HTML file for download or print."""
        from qalens.reports.renderers import render_chat_result_html

        html = render_chat_result_html(
            body.question,
            body.answer,
            body.result,
            autoprint=body.autoprint,
        )
        title = (body.result or {}).get("title", "")
        filename = _safe_filename(str(title)) + ".html"
        return Response(
            content=html,
            media_type="text/html; charset=utf-8",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )

    return router


def _safe_filename(title: str) -> str:
    clean = re.sub(r"[^\w\s-]", "", title.lower()).strip()
    clean = re.sub(r"[\s_-]+", "-", clean)[:50].strip("-")
    return f"qalens-{clean}" if clean else "qalens-chat-result"
