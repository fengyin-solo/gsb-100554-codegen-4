"""保险理赔业务规则：建档、定损、结案与存量回填。"""
from __future__ import annotations

import json
import sqlite3
from typing import Any

from app.db import db_read, db_transaction
from app.errors import Conflict, NotFound, ValidationFailed
from app.money import from_cents, to_cents
from app.schemas_insurance import AssessmentSubmit, ClaimBackfill, ClaimCreate
from app.timeutils import normalize_datetime, now_text

CLAIM_FIELDS_SQL = """
    c.id, c.case_no, c.occurred_at, c.reported_at, c.archived_at,
    c.damaged_equipment, c.estimated_loss_cents, c.deductible_cents,
    c.payout_cap_cents, c.policy_no, c.policy_version, c.policy_terms_json,
    c.status, c.assessment_no, c.assessment_basis, c.assessed_loss_cents,
    c.payout_amount_cents, c.payout_rule, c.closed_at, c.locked,
    c.is_backfilled, c.remark, c.created_at,
    r.status AS receivable_status, r.received_at AS received_at
"""


def _payout_rule(assessed_loss: int, deductible: int, payout_cap: int) -> tuple[int, str]:
    """两条限制冲突时只取赔付更少、对理赔口径更严的一条。"""
    after_deductible = max(assessed_loss - deductible, 0)
    after_cap = min(assessed_loss, payout_cap)
    if after_cap <= after_deductible:
        return after_cap, "赔付上限"
    return after_deductible, "免赔额"


def _parse_time(label: str, value: str) -> str:
    try:
        return normalize_datetime(value)
    except ValueError as exc:
        raise ValidationFailed(f"{label}格式应为 YYYY-MM-DDTHH:MM:SS") from exc


def _row_to_claim(row: sqlite3.Row) -> dict[str, Any]:
    assessed = row["assessed_loss_cents"]
    payout = row["payout_amount_cents"]
    if row["status"] == "已结案":
        payment_status = row["receivable_status"] or ("零赔付结案" if (payout or 0) == 0 else "待收款")
    elif assessed is not None:
        payment_status = "已定款待结案"
    else:
        payment_status = "未定损"

    conclusion = ""
    if payout is not None:
        rule = row["payout_rule"] or "原保单条款"
        if payout == 0:
            conclusion = f"按{rule}从严判定，零赔付结案"
        elif row["status"] == "已结案":
            conclusion = f"按{rule}从严判定，赔付 {from_cents(payout):.2f} 元，已锁定"
        else:
            conclusion = f"按{rule}从严判定，拟赔 {from_cents(payout):.2f} 元"

    return {
        "id": row["id"],
        "案件编号": row["case_no"],
        "出险时间": row["occurred_at"],
        "报案时间": row["reported_at"],
        "建档时间": row["archived_at"],
        "受损设备": row["damaged_equipment"],
        "估损金额": from_cents(row["estimated_loss_cents"]),
        "保单号": row["policy_no"],
        "保单条款": row["policy_version"],
        "保单免赔额": from_cents(row["deductible_cents"]),
        "保单赔付上限": from_cents(row["payout_cap_cents"]),
        "赔付上限": from_cents(row["payout_cap_cents"]),
        "案件状态": row["status"],
        "定损单号": row["assessment_no"],
        "定损口径": row["assessment_basis"],
        "定损金额": from_cents(assessed) if assessed is not None else None,
        "赔付金额": from_cents(payout) if payout is not None else None,
        "从严规则": row["payout_rule"],
        "赔付结论": conclusion,
        "收款状态": payment_status,
        "到账时间": row["received_at"],
        "结案时间": row["closed_at"],
        "已锁定": bool(row["locked"]),
        "存量回填": bool(row["is_backfilled"]),
        "备注": row["remark"],
        "保单条款快照": json.loads(row["policy_terms_json"]),
    }


def _claim_query(where: str = "", params: tuple[Any, ...] = ()) -> tuple[str, tuple[Any, ...]]:
    sql = f"""
        SELECT {CLAIM_FIELDS_SQL}
        FROM insurance_claims c
        LEFT JOIN finance_receivables r ON r.claim_id = c.id
        {where}
        ORDER BY c.archived_at DESC, c.occurred_at DESC, c.id DESC
    """
    return sql, params


class ClaimService:
    def list_entries(
        self,
        *,
        keyword: str | None = None,
        status: str | None = None,
        page: int = 1,
        size: int = 20,
    ) -> tuple[list[dict[str, Any]], int]:
        clauses: list[str] = []
        params: list[Any] = []
        if keyword:
            clauses.append("(c.case_no LIKE ? OR c.damaged_equipment LIKE ?)")
            params.extend([f"%{keyword}%", f"%{keyword}%"])
        if status:
            clauses.append("c.status = ?")
            params.append(status)
        where = "WHERE " + " AND ".join(clauses) if clauses else ""
        with db_read() as connection:
            total = int(connection.execute(
                f"SELECT COUNT(*) FROM insurance_claims c {where}", tuple(params)
            ).fetchone()[0])
            sql, sql_params = _claim_query(where, tuple(params))
            rows = connection.execute(
                sql + " LIMIT ? OFFSET ?",
                (*sql_params, size, max(page - 1, 0) * size),
            ).fetchall()
        return [_row_to_claim(row) for row in rows], total

    def stats(self) -> list[dict[str, Any]]:
        with db_read() as connection:
            status_rows = connection.execute(
                "SELECT status, COUNT(*) FROM insurance_claims GROUP BY status"
            ).fetchall()
            payout_row = connection.execute(
                "SELECT COALESCE(SUM(amount_cents), 0) FROM finance_receivables WHERE status = '待收款'"
            ).fetchone()
        counts = {row[0]: row[1] for row in status_rows}
        return [
            {"label": "待定损案件", "value": counts.get("已报案", 0)},
            {"label": "已定款待结案", "value": counts.get("已定损", 0)},
            {"label": "已结案件", "value": counts.get("已结案", 0)},
            {"label": "财务待收赔款", "value": f"{from_cents(int(payout_row[0])):.2f} 元"},
        ]

    def get_entry(self, entry_id: int) -> dict[str, Any]:
        with db_read() as connection:
            sql, _ = _claim_query("WHERE c.id = ?")
            row = connection.execute(sql, (entry_id,)).fetchone()
        if row is None:
            raise NotFound(f"保险理赔案件 {entry_id} 不存在")
        return _row_to_claim(row)

    def create_entry(self, payload: ClaimCreate) -> dict[str, Any]:
        occurred = _parse_time("出险时间", payload.occurred_at)
        reported = _parse_time("报案时间", payload.reported_at)
        if reported < occurred:
            raise ValidationFailed("报案时间不能早于出险时间")
        terms = {
            "免赔额": str(payload.deductible),
            "赔付上限": str(payload.payout_cap),
            "保单号": payload.policy_no,
            "条款版本": payload.policy_version,
        }
        created_at = now_text()
        try:
            with db_transaction() as connection:
                cursor = connection.execute(
                    """
                    INSERT INTO insurance_claims (
                        case_no, occurred_at, reported_at, archived_at, damaged_equipment,
                        estimated_loss_cents, deductible_cents, payout_cap_cents, policy_no,
                        policy_version, policy_terms_json, status, locked, is_backfilled,
                        remark, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, '已报案', 0, 0, ?, ?)
                    """,
                    (
                        payload.case_no, occurred, reported, reported,
                        payload.damaged_equipment, to_cents(payload.estimated_loss),
                        to_cents(payload.deductible), to_cents(payload.payout_cap),
                        payload.policy_no, payload.policy_version,
                        json.dumps(terms, ensure_ascii=False), payload.remark, created_at,
                    ),
                )
                entry_id = int(cursor.lastrowid)
        except sqlite3.IntegrityError as exc:
            raise Conflict(f"案件编号 {payload.case_no} 已存在") from exc
        return self.get_entry(entry_id)

    def submit_assessment(self, entry_id: int, payload: AssessmentSubmit) -> dict[str, Any]:
        try:
            with db_transaction() as connection:
                claim = connection.execute(
                    "SELECT * FROM insurance_claims WHERE id = ?", (entry_id,)
                ).fetchone()
                if claim is None:
                    raise NotFound(f"保险理赔案件 {entry_id} 不存在")
                if claim["status"] == "已结案" or bool(claim["locked"]):
                    raise Conflict("案件已结案，赔付金额已锁定，定损单不再受理")
                duplicate = connection.execute(
                    "SELECT id, claim_id FROM insurance_assessments WHERE assessment_no = ?",
                    (payload.assessment_no,),
                ).fetchone()
                if duplicate is not None:
                    raise Conflict("该定损单已提交过，仅认第一次提交，原单拒收")

                assessed_cents = to_cents(payload.assessed_loss)
                payout_cents, rule = _payout_rule(
                    assessed_cents,
                    claim["deductible_cents"],
                    claim["payout_cap_cents"],
                )
                submitted_at = now_text()
                connection.execute(
                    """
                    INSERT INTO insurance_assessments (
                        assessment_no, claim_id, assessment_basis, assessed_loss_cents,
                        payout_amount_cents, payout_rule, submitted_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        payload.assessment_no, entry_id, payload.assessment_basis,
                        assessed_cents, payout_cents, rule, submitted_at,
                    ),
                )
                connection.execute(
                    """
                    UPDATE insurance_claims
                    SET assessment_no = ?, assessment_basis = ?, assessed_loss_cents = ?,
                        payout_amount_cents = ?, payout_rule = ?, status = '已定损'
                    WHERE id = ?
                    """,
                    (
                        payload.assessment_no, payload.assessment_basis,
                        assessed_cents, payout_cents, rule, entry_id,
                    ),
                )
        except sqlite3.IntegrityError as exc:
            raise Conflict("定损单或本案件定损记录已存在，仅认第一次提交") from exc
        return self.get_entry(entry_id)

    def close_entry(self, entry_id: int) -> dict[str, Any]:
        closed_at = now_text()
        try:
            with db_transaction() as connection:
                claim = connection.execute(
                    "SELECT * FROM insurance_claims WHERE id = ?", (entry_id,)
                ).fetchone()
                if claim is None:
                    raise NotFound(f"保险理赔案件 {entry_id} 不存在")
                if claim["status"] == "已结案":
                    raise Conflict("案件已结案，赔付金额已锁定")
                if claim["payout_amount_cents"] is None:
                    raise ValidationFailed("定损结论尚未形成，不能结案")
                connection.execute(
                    """
                    UPDATE insurance_claims
                    SET status = '已结案', locked = 1, closed_at = ?
                    WHERE id = ?
                    """,
                    (closed_at, entry_id),
                )
                amount = int(claim["payout_amount_cents"])
                receivable_status = "待收款" if amount > 0 else "零赔付结案"
                connection.execute(
                    """
                    INSERT INTO finance_receivables (
                        receivable_no, claim_id, case_no, source, amount_cents, currency,
                        status, created_at
                    ) VALUES (?, ?, ?, '保险理赔', ?, 'CNY', ?, ?)
                    """,
                    (
                        f"AR-{claim['case_no']}", entry_id, claim["case_no"],
                        amount, receivable_status, closed_at,
                    ),
                )
        except sqlite3.IntegrityError as exc:
            raise Conflict("案件已结案或财务待收款记录已存在") from exc
        return self.get_entry(entry_id)

    def backfill_entry(self, payload: ClaimBackfill) -> dict[str, Any]:
        occurred = _parse_time("出险时间", payload.occurred_at)
        reported = _parse_time("报案时间", payload.reported_at) if payload.reported_at else None
        closed_at = _parse_time("结案时间", payload.closed_at) if payload.closed_at else None
        archived_at = occurred
        target_status = payload.status or ("已结案" if payload.closed else ("已定损" if payload.assessment_no else "已报案"))
        if target_status not in {"已报案", "已定损", "已结案"}:
            raise ValidationFailed("回填状态只能是已报案、已定损或已结案")
        if target_status in {"已定损", "已结案"}:
            missing = [
                name for name, value in {
                    "定损单号": payload.assessment_no,
                    "定损口径": payload.assessment_basis,
                    "定损金额": payload.assessed_loss,
                }.items()
                if value is None
            ]
            if missing:
                raise ValidationFailed(f"已定损存量案件缺少：{'、'.join(missing)}")
        elif payload.payout_rule or payload.assessed_loss is not None:
            raise ValidationFailed("已报案存量案件不能回填定损结论")
        closed = bool(payload.closed or target_status == "已结案")
        if payload.assessed_loss is not None:
            payout_cents, calculated_rule = _payout_rule(
                to_cents(payload.assessed_loss),
                to_cents(payload.deductible),
                to_cents(payload.payout_cap),
            )
            if payload.payout_rule and payload.payout_rule not in {"免赔额", "赔付上限"}:
                raise ValidationFailed("从严规则只能是免赔额或赔付上限")
            rule = payload.payout_rule or calculated_rule
        else:
            payout_cents = None
            rule = None
        terms = {
            "免赔额": str(payload.deductible),
            "赔付上限": str(payload.payout_cap),
            "保单号": payload.policy_no,
            "条款版本": payload.policy_version,
            "存量回填": True,
        }
        created_at = now_text()
        try:
            with db_transaction() as connection:
                cursor = connection.execute(
                    """
                    INSERT INTO insurance_claims (
                        case_no, occurred_at, reported_at, archived_at, damaged_equipment,
                        estimated_loss_cents, deductible_cents, payout_cap_cents, policy_no,
                        policy_version, policy_terms_json, status, assessment_no,
                        assessment_basis, assessed_loss_cents, payout_amount_cents,
                        payout_rule, closed_at, locked, is_backfilled, remark, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?)
                    """,
                    (
                        payload.case_no, occurred, reported, archived_at,
                        payload.damaged_equipment, to_cents(payload.estimated_loss),
                        to_cents(payload.deductible), to_cents(payload.payout_cap),
                        payload.policy_no, payload.policy_version,
                        json.dumps(terms, ensure_ascii=False), target_status,
                        payload.assessment_no, payload.assessment_basis,
                        to_cents(payload.assessed_loss) if payload.assessed_loss is not None else None,
                        payout_cents, rule, closed_at or (created_at if closed else None),
                        1 if closed else 0,
                        "存量案件按出险时间回填" if not payload.remark else payload.remark,
                        created_at,
                    ),
                )
                entry_id = int(cursor.lastrowid)
                if payload.assessment_no:
                    connection.execute(
                        """
                        INSERT INTO insurance_assessments (
                            assessment_no, claim_id, assessment_basis, assessed_loss_cents,
                            payout_amount_cents, payout_rule, submitted_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            payload.assessment_no, entry_id, payload.assessment_basis,
                            to_cents(payload.assessed_loss), payout_cents, rule,
                            created_at,
                        ),
                    )
                if closed:
                    amount = payout_cents or 0
                    finance_status = "已收款" if payload.received else ("零赔付结案" if amount == 0 else "待收款")
                    connection.execute(
                        """
                        INSERT INTO finance_receivables (
                            receivable_no, claim_id, case_no, source, amount_cents,
                            currency, status, created_at
                        ) VALUES (?, ?, ?, '保险理赔', ?, 'CNY', ?, ?)
                        """,
                        (
                            f"AR-{payload.case_no}", entry_id, payload.case_no,
                            amount, finance_status, closed_at or created_at,
                        ),
                    )
        except sqlite3.IntegrityError as exc:
            raise Conflict(f"案件编号 {payload.case_no} 或定损单号已存在") from exc
        return self.get_entry(entry_id)
