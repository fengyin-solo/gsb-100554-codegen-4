"""财务待收款台账规则。"""
from __future__ import annotations

import sqlite3
from typing import Any

from app.db import db_read, db_transaction
from app.errors import Conflict, NotFound, ValidationFailed
from app.money import from_cents
from app.timeutils import normalize_datetime, now_text


def _row_to_receivable(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "待收款编号": row["receivable_no"],
        "案件编号": row["case_no"],
        "款项来源": row["source"],
        "应收金额": from_cents(row["amount_cents"]),
        "币种": row["currency"],
        "收款状态": row["status"],
        "预计到账日": row["expected_at"],
        "到账时间": row["received_at"],
        "建档时间": row["created_at"],
    }


class FinanceReceivableService:
    def list_entries(
        self,
        *,
        status: str | None = None,
        page: int = 1,
        size: int = 20,
    ) -> tuple[list[dict[str, Any]], int]:
        where = ""
        params: tuple[Any, ...] = ()
        if status:
            where = "WHERE status = ?"
            params = (status,)
        with db_read() as connection:
            total = int(connection.execute(
                f"SELECT COUNT(*) FROM finance_receivables {where}", params
            ).fetchone()[0])
            rows = connection.execute(
                f"""
                SELECT * FROM finance_receivables
                {where}
                ORDER BY created_at DESC, id DESC
                LIMIT ? OFFSET ?
                """,
                (*params, size, max(page - 1, 0) * size),
            ).fetchall()
        return [_row_to_receivable(row) for row in rows], total

    def stats(self) -> list[dict[str, Any]]:
        with db_read() as connection:
            rows = connection.execute(
                "SELECT status, COUNT(*), COALESCE(SUM(amount_cents), 0) FROM finance_receivables GROUP BY status"
            ).fetchall()
        stat_map = {row[0]: (row[1], int(row[2])) for row in rows}
        pending_count, pending_amount = stat_map.get("待收款", (0, 0))
        received_count, received_amount = stat_map.get("已收款", (0, 0))
        zero_count, _ = stat_map.get("零赔付结案", (0, 0))
        return [
            {"label": "待收款笔数", "value": pending_count},
            {"label": "待收金额", "value": f"{from_cents(pending_amount):.2f} 元"},
            {"label": "已收款笔数", "value": received_count},
            {"label": "已收金额", "value": f"{from_cents(received_amount):.2f} 元"},
            {"label": "零赔付结案", "value": zero_count},
        ]

    def get_entry(self, entry_id: int) -> dict[str, Any]:
        with db_read() as connection:
            row = connection.execute(
                "SELECT * FROM finance_receivables WHERE id = ?", (entry_id,)
            ).fetchone()
        if row is None:
            raise NotFound(f"待收款记录 {entry_id} 不存在")
        return _row_to_receivable(row)

    def confirm_received(self, entry_id: int, received_at: str | None = None) -> dict[str, Any]:
        try:
            received_text = normalize_datetime(received_at) if received_at else now_text()
        except ValueError as exc:
            raise ValidationFailed("到账时间格式应为 YYYY-MM-DDTHH:MM:SS") from exc
        with db_transaction() as connection:
            row = connection.execute(
                "SELECT * FROM finance_receivables WHERE id = ?", (entry_id,)
            ).fetchone()
            if row is None:
                raise NotFound(f"待收款记录 {entry_id} 不存在")
            if row["status"] == "已收款":
                raise Conflict("该笔赔款已经确认到账，收款状态不能重复修改")
            if row["status"] == "零赔付结案" or int(row["amount_cents"]) == 0:
                raise Conflict("零赔付案件没有待收款项，不能确认到账")
            connection.execute(
                """
                UPDATE finance_receivables
                SET status = '已收款', received_at = ?
                WHERE id = ?
                """,
                (received_text, entry_id),
            )
        return self.get_entry(entry_id)
