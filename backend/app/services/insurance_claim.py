"""保险理赔案件业务规则：报案建档、定损口径判定、赔付结论落台账与结案锁死。

赔付口径：免赔额规则（定损金额 - 免赔额）与赔付上限规则（不超过赔付上限）
冲突时只执行更严的那条，判定依据只保留一种，结论计算一次后存回案件行，
列表与详情读到的始终是同一份结论。
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any

from app.services.claim_persistence import persist, restore
from app.store import store

MODULE = "insurance_claim"
RECEIVABLE_MODULE = "claim_receivable"
REQUIRED_FIELDS = ["出险时间", "报案时间", "受损设备", "估损金额", "保单号", "免赔额", "赔付上限"]
AMOUNT_FIELDS = ["估损金额", "免赔额", "赔付上限"]
STATUS_ORDER = ["已报案", "待赔付", "已结案"]
ACTIONS = ["提交定损", "结案"]

RULE_DEDUCTIBLE = "免赔额规则从严"
RULE_CAP = "赔付上限规则从严"


def _parse_amount(raw: Any) -> Decimal | None:
    """把外部传入的金额解析成两位小数的 Decimal；非数字或负数返回 None。"""
    try:
        value = Decimal(str(raw).replace(",", "").strip())
    except (InvalidOperation, ValueError):
        return None
    if value < 0:
        return None
    return value.quantize(Decimal("0.01"))


def _to_number(value: Decimal) -> float:
    return float(value)


def judge_payout(assessed: Decimal, deductible: Decimal, cap: Decimal) -> tuple[Decimal, str]:
    """按定损口径从严判定赔付金额：两条规则各算一遍，只保留更严的那条结论。"""
    by_deductible = max(assessed - deductible, Decimal("0.00"))
    by_cap = min(assessed, cap)
    if by_deductible <= by_cap:
        return by_deductible, RULE_DEDUCTIBLE
    return by_cap, RULE_CAP


def _next_code(rows: list[dict[str, Any]], field: str, prefix: str) -> str:
    max_seq = 0
    for row in rows:
        code = str(row.get(field) or "")
        if code.startswith(prefix):
            try:
                max_seq = max(max_seq, int(code[len(prefix):]))
            except ValueError:
                continue
    return f"{prefix}{max_seq + 1:04d}"


class InsuranceClaimService:
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
                if keyword in str(row.get("案件编号", "")) or keyword in str(row.get("受损设备", ""))
            ]
        if status:
            rows = [row for row in rows if row.get("status") == status]
        # 台账按出险报案时间建档排序，时间与列表口径保持一致
        rows = sorted(rows, key=lambda row: (str(row.get("报案时间") or ""), int(row.get("id", 0))))
        total = len(rows)
        start = max(page - 1, 0) * size
        return rows[start:start + size], total

    def get_entry(self, entry_id: int) -> dict[str, Any] | None:
        return store.find(MODULE, entry_id)

    def create_entry(self, values: dict[str, Any]) -> tuple[dict[str, Any] | None, str]:
        missing = [field for field in REQUIRED_FIELDS if not str(values.get(field) or "").strip()]
        if missing:
            return None, f"缺少必填字段：{'、'.join(missing)}"
        amounts: dict[str, float] = {}
        for field in AMOUNT_FIELDS:
            parsed = _parse_amount(values.get(field))
            if parsed is None:
                return None, f"{field}需为非负数字"
            amounts[field] = _to_number(parsed)
        rows = store.rows(MODULE)
        code = str(values.get("案件编号") or "").strip()
        if code:
            if any(row.get("案件编号") == code for row in rows):
                return None, f"案件编号 {code} 已存在，请勿重复建档"
        else:
            code = _next_code(rows, "案件编号", "CLM-")
        entry: dict[str, Any] = {"id": max((int(row.get("id", 0)) for row in rows), default=0) + 1}
        entry["案件编号"] = code
        for field in REQUIRED_FIELDS:
            entry[field] = amounts[field] if field in amounts else str(values.get(field)).strip()
        # 定损与赔付结论字段留空，等定损单提交后一次性写入
        for field in ["定损单号", "定损金额", "定损时间", "赔付金额", "判定依据", "收款状态", "结案时间"]:
            entry[field] = None
        entry["status"] = STATUS_ORDER[0]
        entry["pending"] = True
        entry["abnormal"] = False
        rows.append(entry)
        persist()
        return entry, f"理赔案件 {code} 已登记，等待提交定损"

    def run_action(
        self, entry_id: int, action: str, values: dict[str, Any]
    ) -> tuple[dict[str, Any] | None, str]:
        entry = store.find(MODULE, entry_id)
        if entry is None:
            return None, f"理赔案件 {entry_id} 不存在或已归档"
        if action == "提交定损":
            return self._submit_assessment(entry, values)
        if action == "结案":
            return self._close(entry)
        return None, f"动作「{action}」不属于保险理赔可执行范围"

    def _submit_assessment(
        self, entry: dict[str, Any], values: dict[str, Any]
    ) -> tuple[dict[str, Any] | None, str]:
        if entry.get("status") == "已结案":
            return None, f"案件 {entry['案件编号']} 已结案，赔付金额已锁死，定损结论不再变更"
        if entry.get("定损单号"):
            return None, f"案件 {entry['案件编号']} 已按定损单 {entry['定损单号']} 定损，重复定损不予受理"
        assess_no = str(values.get("定损单号") or "").strip()
        if not assess_no:
            return None, "提交定损需填写定损单号"
        # 同一张定损单重复提交只认第一次，后来的原样拒收
        for row in store.rows(MODULE):
            if row.get("定损单号") == assess_no:
                return None, f"定损单 {assess_no} 已受理并生成赔付结论，重复提交原样拒收"
        assessed = _parse_amount(values.get("定损金额"))
        if assessed is None:
            return None, "定损金额需为非负数字"
        deductible = _parse_amount(entry.get("免赔额"))
        cap = _parse_amount(entry.get("赔付上限"))
        if deductible is None or cap is None:
            return None, "案件缺少有效的免赔额或赔付上限快照，无法判定赔付"
        payout, rule = judge_payout(assessed, deductible, cap)
        entry["定损单号"] = assess_no
        entry["定损金额"] = _to_number(assessed)
        entry["定损时间"] = date.today().isoformat()
        entry["赔付金额"] = _to_number(payout)
        entry["判定依据"] = rule
        entry["status"] = "待赔付"
        self._register_receivable(entry)
        persist()
        return entry, f"定损单 {assess_no} 已受理，赔付金额 {entry['赔付金额']:.2f} 元（{rule}）"

    def _register_receivable(self, entry: dict[str, Any]) -> None:
        """赔付结论落到财务待收款台账；赔付为 0 时无需收款，不占台账。"""
        payout = float(entry.get("赔付金额") or 0)
        if payout <= 0:
            entry["收款状态"] = "无需收款"
            return
        rows = store.rows(RECEIVABLE_MODULE)
        rows.append({
            "id": max((int(row.get("id", 0)) for row in rows), default=0) + 1,
            "status": "待收款",
            "pending": True,
            "abnormal": False,
            "台账编号": _next_code(rows, "台账编号", "REC-"),
            "案件编号": entry["案件编号"],
            "赔付金额": payout,
            "收款状态": "待收款",
            "登记时间": date.today().isoformat(),
            "收款时间": None,
        })
        entry["收款状态"] = "待收款"

    def _close(self, entry: dict[str, Any]) -> tuple[dict[str, Any] | None, str]:
        if entry.get("status") == "已结案":
            return None, f"案件 {entry['案件编号']} 已结案，赔付金额处于锁死状态"
        if entry.get("status") != "待赔付":
            return None, f"案件 {entry['案件编号']} 尚未提交定损，不能结案"
        entry["status"] = "已结案"
        entry["pending"] = False
        entry["结案时间"] = date.today().isoformat()
        persist()
        return entry, f"案件 {entry['案件编号']} 已结案，赔付金额 {entry['赔付金额']:.2f} 元已锁死"
