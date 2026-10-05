"""财务待收款台账接口。"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body, Query

from app.errors import ValidationFailed
from app.schemas import PageResult
from app.schemas_insurance import ReceivableConfirm
from app.services.finance_receivable import FinanceReceivableService

router = APIRouter(prefix="/api/finance_receivables", tags=["财务待收款"])
service = FinanceReceivableService()


@router.get("/stats")
def receivable_stats() -> dict[str, Any]:
    return {"items": service.stats()}


@router.get("", response_model=PageResult[dict])
def list_entries(
    status: str | None = Query(default=None, description="待收款、已收款、零赔付结案"),
    page: int = 1,
    size: int = 20,
) -> PageResult[dict]:
    if page < 1:
        raise ValidationFailed("页码必须大于 0")
    if size < 1:
        raise ValidationFailed("每页条数必须大于 0")
    if size > 200:
        raise ValidationFailed("每页最多 200 条，请缩小分页范围")
    items, total = service.list_entries(status=status, page=page, size=size)
    return PageResult(items=items, total=total, page=page, size=size)


@router.get("/export")
def export_entries() -> dict[str, Any]:
    items, total = service.list_entries(page=1, size=10000)
    return {"module": "finance_receivable", "total": total, "items": items}


@router.get("/{entry_id}")
def get_entry(entry_id: int) -> dict[str, Any]:
    return service.get_entry(entry_id)


@router.post("/{entry_id}/confirm-received")
@router.post("/{entry_id}/confirm")
def confirm_received(
    entry_id: int,
    payload: ReceivableConfirm = Body(default_factory=ReceivableConfirm),
) -> dict[str, Any]:
    entry = service.confirm_received(entry_id, payload.received_at)
    return {"ok": True, "message": "赔款到账已确认，案件收款状态同步更新", "entry": entry}
