"""保险理赔案件接口。"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Query

from app.errors import ValidationFailed
from app.schemas import ActionResult, PageResult
from app.schemas_insurance import AssessmentSubmit, ClaimBackfill, ClaimCreate
from app.services.insurance_claim import ClaimService

router = APIRouter(prefix="/api/insurance_claims", tags=["保险理赔"])
service = ClaimService()


@router.get("/stats")
def claim_stats() -> dict[str, Any]:
    return {"items": service.stats()}


@router.get("", response_model=PageResult[dict])
def list_entries(
    keyword: str | None = Query(default=None, description="按案件编号或受损设备检索"),
    status: str | None = Query(default=None, description="已报案、已定损、已结案"),
    page: int = 1,
    size: int = 20,
) -> PageResult[dict]:
    if page < 1:
        raise ValidationFailed("页码必须大于 0")
    if size < 1:
        raise ValidationFailed("每页条数必须大于 0")
    if size > 200:
        raise ValidationFailed("每页最多 200 条，请缩小分页范围")
    items, total = service.list_entries(keyword=keyword, status=status, page=page, size=size)
    return PageResult(items=items, total=total, page=page, size=size)


@router.post("")
def create_entry(payload: ClaimCreate) -> dict[str, Any]:
    entry = service.create_entry(payload)
    return {"ok": True, "message": "出险报案已按报案时间建档", "entry": entry}


@router.post("/backfill")
def backfill_entry(payload: ClaimBackfill) -> dict[str, Any]:
    entry = service.backfill_entry(payload)
    return {"ok": True, "message": "存量案件已按出险时间回填，并沿用原保单条款", "entry": entry}


@router.get("/export")
def export_entries() -> dict[str, Any]:
    items, total = service.list_entries(page=1, size=10000)
    return {"module": "insurance_claim", "total": total, "items": items}


@router.get("/{entry_id}")
def get_entry(entry_id: int) -> dict[str, Any]:
    return service.get_entry(entry_id)


@router.post("/{entry_id}/assessment")
@router.post("/{entry_id}/assessments")
def submit_assessment(entry_id: int, payload: AssessmentSubmit) -> dict[str, Any]:
    entry = service.submit_assessment(entry_id, payload)
    return {"ok": True, "message": "定损单已受理，赔付结论按更严规则生成", "entry": entry}


@router.post("/{entry_id}/actions", response_model=ActionResult)
def run_action(entry_id: int, payload: dict[str, Any]) -> ActionResult:
    """兼容统一动作入口：支持提交定损和结案锁定。"""
    values = payload.get("values") if isinstance(payload.get("values"), dict) else payload
    action = str(values.get("action") or "").strip()
    if action in {"结案锁定", "结案"}:
        entry = service.close_entry(entry_id)
        return ActionResult(ok=True, message="案件已结案，赔付金额已锁定并写入财务待收款台账", entry=entry)
    if action == "提交定损":
        def pick(*names: str) -> Any:
            for name in names:
                if name in values and values.get(name) is not None:
                    return values.get(name)
            return None

        assessment = AssessmentSubmit(
            assessment_no=pick("assessment_no", "定损单号"),
            assessment_basis=pick("assessment_basis", "定损口径"),
            assessed_loss=pick("assessed_loss", "定损金额"),
        )
        entry = service.submit_assessment(entry_id, assessment)
        return ActionResult(ok=True, message="定损单已受理，赔付结论按更严规则生成", entry=entry)
    raise ValidationFailed("仅支持提交定损、结案锁定动作")


@router.post("/{entry_id}/close")
@router.post("/{entry_id}/settle")
def close_entry(entry_id: int) -> dict[str, Any]:
    entry = service.close_entry(entry_id)
    return {"ok": True, "message": "案件已结案，赔付金额已锁定并写入财务待收款台账", "entry": entry}
