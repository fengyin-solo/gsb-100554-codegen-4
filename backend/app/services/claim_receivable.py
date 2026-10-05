"""财务待收款台账业务规则：赔付结论自动生成台账记录，登记收款后回写案件收款状态。"""
from __future__ import annotations

from datetime import date
from typing import Any

from app.services.claim_persistence import persist, restore
from app.store import store

MODULE = "claim_receivable"
CLAIM_MODULE = "insurance_claim"
ACTIONS = ["登记收款"]


class ClaimReceivableService:
    def __init__(self) -> None:
        restore()

    def list_entries(
        self,
        *,
        keyword: str | None = None,
        status: str | None = None,
        page: int = 1,
        size: int = 20,
    ) -> tuple[list[dict[str, Any]], int]:
        rows = store.rows(MODULE)
        if keyword:
            rows = [
                row
                for row in rows
                if keyword in str(row.get("台账编号", "")) or keyword in str(row.get("案件编号", ""))
            ]
        if status:
            rows = [row for row in rows if row.get("收款状态") == status]
        rows = sorted(rows, key=lambda row: (str(row.get("登记时间") or ""), int(row.get("id", 0))))
        total = len(rows)
        start = max(page - 1, 0) * size
        return rows[start:start + size], total

    def get_entry(self, entry_id: int) -> dict[str, Any] | None:
        return store.find(MODULE, entry_id)

    def run_action(self, entry_id: int, action: str) -> tuple[dict[str, Any] | None, str]:
        entry = store.find(MODULE, entry_id)
        if entry is None:
            return None, f"待收款台账 {entry_id} 不存在或已归档"
        if action != "登记收款":
            return None, f"动作「{action}」不属于待收款台账可执行范围"
        if entry.get("收款状态") == "已收款":
            return None, f"台账 {entry['台账编号']} 已收款，请勿重复登记"
        entry["收款状态"] = "已收款"
        entry["status"] = "已收款"
        entry["pending"] = False
        entry["收款时间"] = date.today().isoformat()
        # 收款状态随之回写理赔案件，两处读到同一结论
        for claim in store.rows(CLAIM_MODULE):
            if claim.get("案件编号") == entry.get("案件编号"):
                claim["收款状态"] = "已收款"
                break
        persist()
        return entry, f"台账 {entry['台账编号']} 已登记收款 {entry['赔付金额']:.2f} 元"
