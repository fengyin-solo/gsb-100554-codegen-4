"""SQLite 持久化连接与保险理赔表结构。"""
from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from typing import Iterator

from app.config import settings
from app.money import to_cents

SCHEMA_SQL = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS insurance_claims (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    case_no TEXT NOT NULL UNIQUE,
    occurred_at TEXT NOT NULL,
    reported_at TEXT,
    archived_at TEXT NOT NULL,
    damaged_equipment TEXT NOT NULL,
    estimated_loss_cents INTEGER NOT NULL,
    deductible_cents INTEGER NOT NULL,
    payout_cap_cents INTEGER NOT NULL,
    policy_no TEXT,
    policy_version TEXT NOT NULL,
    policy_terms_json TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('已报案', '已定损', '已结案')),
    assessment_no TEXT,
    assessment_basis TEXT,
    assessed_loss_cents INTEGER,
    payout_amount_cents INTEGER,
    payout_rule TEXT,
    closed_at TEXT,
    locked INTEGER NOT NULL DEFAULT 0,
    is_backfilled INTEGER NOT NULL DEFAULT 0,
    remark TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS insurance_assessments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    assessment_no TEXT NOT NULL UNIQUE,
    claim_id INTEGER NOT NULL,
    assessment_basis TEXT NOT NULL,
    assessed_loss_cents INTEGER NOT NULL,
    payout_amount_cents INTEGER NOT NULL,
    payout_rule TEXT NOT NULL,
    submitted_at TEXT NOT NULL,
    FOREIGN KEY (claim_id) REFERENCES insurance_claims(id)
);

CREATE TABLE IF NOT EXISTS finance_receivables (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    receivable_no TEXT NOT NULL UNIQUE,
    claim_id INTEGER NOT NULL UNIQUE,
    case_no TEXT NOT NULL,
    source TEXT NOT NULL,
    amount_cents INTEGER NOT NULL,
    currency TEXT NOT NULL DEFAULT 'CNY',
    status TEXT NOT NULL CHECK (status IN ('待收款', '已收款', '零赔付结案')),
    expected_at TEXT,
    received_at TEXT,
    created_at TEXT NOT NULL,
    FOREIGN KEY (claim_id) REFERENCES insurance_claims(id)
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_insurance_assessments_claim
ON insurance_assessments(claim_id);
CREATE INDEX IF NOT EXISTS idx_insurance_claims_archived_at ON insurance_claims(archived_at);
CREATE INDEX IF NOT EXISTS idx_insurance_claims_occurred_at ON insurance_claims(occurred_at);
CREATE INDEX IF NOT EXISTS idx_insurance_claims_status ON insurance_claims(status);
CREATE INDEX IF NOT EXISTS idx_finance_receivables_status ON finance_receivables(status);
"""

LEGACY_CLAIMS = [
    {
        "case_no": "CLM-2024-001",
        "occurred_at": "2024-05-12T09:30:00",
        "reported_at": "2024-05-12T10:05:00",
        "damaged_equipment": "1号集中式逆变器",
        "estimated_loss": "180000",
        "deductible": "10000",
        "payout_cap": "150000",
        "policy_no": "POL-2024-EQ-01",
        "policy_version": "2024版保单条款",
        "assessment_no": "AS-2024-001",
        "assessment_basis": "维修报价核定",
        "assessed_loss": "160000",
        "status": "已结案",
        "received": True,
        "expected_at": "2024-07-15T00:00:00",
        "closed_at": "2024-06-28T15:00:00",
        "received_at": "2024-07-12T11:20:00",
    },
    {
        "case_no": "CLM-2025-006",
        "occurred_at": "2025-03-08T14:20:00",
        "reported_at": "2025-03-08T16:00:00",
        "damaged_equipment": "2号主变压器冷却风机",
        "estimated_loss": "95000",
        "deductible": "8000",
        "payout_cap": "120000",
        "policy_no": "POL-2025-EQ-02",
        "policy_version": "2025版保单条款",
        "assessment_no": "AS-2025-006",
        "assessment_basis": "更换费用核定",
        "assessed_loss": "88000",
        "status": "已结案",
        "received": False,
        "expected_at": "2025-05-20T00:00:00",
        "closed_at": "2025-04-26T10:30:00",
        "received_at": None,
    },
    {
        "case_no": "CLM-2026-002",
        "occurred_at": "2026-01-19T06:45:00",
        "reported_at": "2026-01-19T07:30:00",
        "damaged_equipment": "北区汇流箱熔断器组",
        "estimated_loss": "52000",
        "deductible": "5000",
        "payout_cap": "60000",
        "policy_no": "POL-2026-EQ-01",
        "policy_version": "2026版保单条款",
        "assessment_no": "AS-2026-002",
        "assessment_basis": "检测及维修核定",
        "assessed_loss": "47000",
        "status": "已定损",
        "received": False,
        "expected_at": None,
        "closed_at": None,
        "received_at": None,
    },
    {
        "case_no": "CLM-2026-003",
        "occurred_at": "2026-02-02T21:10:00",
        "reported_at": "2026-02-03T08:15:00",
        "damaged_equipment": "储能 PCS 控制板",
        "estimated_loss": "70000",
        "deductible": "6000",
        "payout_cap": "65000",
        "policy_no": "POL-2026-EQ-01",
        "policy_version": "2026版保单条款",
        "assessment_no": None,
        "assessment_basis": None,
        "assessed_loss": None,
        "status": "已报案",
        "received": False,
        "expected_at": None,
        "closed_at": None,
        "received_at": None,
    },
]


def _connect() -> sqlite3.Connection:
    connection = sqlite3.connect(settings.database_path, timeout=30)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


@contextmanager
def db_transaction() -> Iterator[sqlite3.Connection]:
    connection = _connect()
    try:
        yield connection
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


@contextmanager
def db_read() -> Iterator[sqlite3.Connection]:
    connection = _connect()
    try:
        yield connection
    finally:
        connection.close()


def initialize_database() -> None:
    with db_transaction() as connection:
        connection.executescript(SCHEMA_SQL)
        _seed_legacy_claims(connection)


def _calculate_seed_payout(row: dict[str, object]) -> tuple[int, str]:
    assessed = to_cents(row["assessed_loss"])
    after_deductible = max(assessed - to_cents(row["deductible"]), 0)
    capped = min(assessed, to_cents(row["payout_cap"]))
    if capped <= after_deductible:
        return capped, "赔付上限"
    return after_deductible, "免赔额"


def _seed_legacy_claims(connection: sqlite3.Connection) -> None:
    existing = {
        row["case_no"]
        for row in connection.execute("SELECT case_no FROM insurance_claims WHERE is_backfilled = 1")
    }
    for seed in LEGACY_CLAIMS:
        if seed["case_no"] in existing:
            continue
        terms = {
            "免赔额": seed["deductible"],
            "赔付上限": seed["payout_cap"],
            "存量案件": True,
            "沿用条款": seed["policy_version"],
        }
        payout = None
        payout_rule = None
        if seed["assessed_loss"] is not None:
            payout, payout_rule = _calculate_seed_payout(seed)
        is_closed = seed["status"] == "已结案"
        archived_at = seed["occurred_at"]
        cursor = connection.execute(
            """
            INSERT INTO insurance_claims (
                case_no, occurred_at, reported_at, archived_at, damaged_equipment,
                estimated_loss_cents, deductible_cents, payout_cap_cents, policy_no,
                policy_version, policy_terms_json, status, assessment_no,
                assessment_basis, assessed_loss_cents, payout_amount_cents,
                payout_rule, closed_at, locked, is_backfilled, remark, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                seed["case_no"], seed["occurred_at"], seed["reported_at"], archived_at,
                seed["damaged_equipment"], to_cents(seed["estimated_loss"]),
                to_cents(seed["deductible"]), to_cents(seed["payout_cap"]),
                seed["policy_no"], seed["policy_version"], json.dumps(terms, ensure_ascii=False), seed["status"],
                seed["assessment_no"], seed["assessment_basis"],
                to_cents(seed["assessed_loss"]) if seed["assessed_loss"] is not None else None,
                payout, payout_rule, seed["closed_at"], 1 if is_closed else 0, 1,
                "存量案件按出险时间回填", archived_at,
            ),
        )
        claim_id = int(cursor.lastrowid)
        if seed["assessment_no"]:
            connection.execute(
                """
                INSERT INTO insurance_assessments (
                    assessment_no, claim_id, assessment_basis, assessed_loss_cents,
                    payout_amount_cents, payout_rule, submitted_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    seed["assessment_no"], claim_id, seed["assessment_basis"],
                    to_cents(seed["assessed_loss"]), payout, payout_rule,
                    f"{seed['closed_at']}" if is_closed else seed["reported_at"],
                ),
            )
        if is_closed:
            status = "已收款" if seed["received"] else "待收款"
            received_at = seed["received_at"]
            connection.execute(
                """
                INSERT INTO finance_receivables (
                    receivable_no, claim_id, case_no, source, amount_cents, currency,
                    status, expected_at, received_at, created_at
                ) VALUES (?, ?, ?, ?, ?, 'CNY', ?, ?, ?, ?)
                """,
                (
                    f"AR-{seed['case_no']}", claim_id, seed["case_no"], "保险理赔",
                    payout, status, seed["expected_at"], received_at, seed["closed_at"],
                ),
            )
