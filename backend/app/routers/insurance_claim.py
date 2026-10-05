"""保险理赔接口：报案建档、定损提交、结案；赔付结论列表与详情同源于案件行。"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query

from app.schemas import ActionResult, EntryPayload, PageResult
from app.services.insurance_claim import InsuranceClaimService

router = APIRouter(prefix="/api/insurance_claim", tags=["保险理赔"])

service = InsuranceClaimService()

STATUSES = ["已报案", "待赔付", "已结案"]


@router.get("", response_model=PageResult[dict])
def list_entries(
    keyword: str | None = Query(default=None, description="按案件编号或受损设备检索"),
    status: str | None = Query(default=None, description="已报案、待赔付、已结案"),
    page: int = 1,
    size: int = 20,
) -> PageResult[dict]:
    """按出险报案时间列出理赔案件；没有数据时返回空页，不报错。"""
    if size > 200:
        raise HTTPException(status_code=400, detail="每页最多 200 条，请缩小分页范围")
    items, total = service.list_entries(keyword=keyword, status=status, page=page, size=size)
    return PageResult(items=items, total=total, page=page, size=size)


@router.get("/export")
def export_entries() -> dict[str, Any]:
    """导出保险理赔台账：返回当前过滤条件下的全量数据。"""
    items, total = service.list_entries(page=1, size=10000)
    return {"module": "insurance_claim", "total": total, "items": items}


@router.get("/{entry_id}", response_model=dict)
def get_entry(entry_id: int) -> dict:
    """读取单条理赔案件详情；赔付结论与列表同源，不存在两个口径。"""
    entry = service.get_entry(entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"理赔案件 {entry_id} 不存在或已归档")
    return entry


@router.post("", response_model=ActionResult)
def create_entry(payload: EntryPayload) -> ActionResult:
    """登记出险报案：记录受损设备、估损金额与保单免赔额、赔付上限快照。"""
    entry, message = service.create_entry(payload.values)
    if entry is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message=message, entry=entry)


@router.post("/{entry_id}/actions", response_model=ActionResult)
def run_action(entry_id: int, payload: EntryPayload) -> ActionResult:
    """对单条理赔案件执行提交定损、结案；重复定损单与结案后变更都会被拦下。"""
    action = str(payload.values.get("action") or "").strip()
    entry, message = service.run_action(entry_id, action, payload.values)
    if entry is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message=message, entry=entry)
