"""理赔数据落库：赔付结论与待收款台账每次变更即写盘，服务重启后原样恢复。

真实项目里这里会换成数据库事务写入；当前用 JSON 文件保证克隆下来就能跑，
同时满足"赔付数据要落库"的要求。种子数据只在首次启动（落库文件不存在）时生效。
"""
from __future__ import annotations

import json
from pathlib import Path

from app.store import store

MODULES = ("insurance_claim", "claim_receivable")
DATA_DIR = Path(__file__).resolve().parents[2] / "data"
LEDGER_FILE = DATA_DIR / "insurance_claim_ledger.json"

_restored = False


def restore() -> None:
    """启动时把落库的理赔台账读回内存仓库；没有落库文件时沿用种子回填数据。"""
    global _restored
    if _restored:
        return
    _restored = True
    if not LEDGER_FILE.exists():
        return
    try:
        payload = json.loads(LEDGER_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return  # 落库文件损坏时保留种子数据并继续启动，由下次写盘修复
    for module in MODULES:
        rows = payload.get(module)
        if isinstance(rows, list):
            store.rows(module)[:] = [dict(row) for row in rows]


def persist() -> None:
    """把理赔与待收款两个台账整体写盘；先写临时文件再替换，避免半截文件。"""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    payload = {module: store.rows(module) for module in MODULES}
    tmp_file = LEDGER_FILE.with_suffix(".tmp")
    tmp_file.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp_file.replace(LEDGER_FILE)
