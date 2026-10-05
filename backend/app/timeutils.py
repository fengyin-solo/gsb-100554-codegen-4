"""时间字段的统一解析与生成。"""
from __future__ import annotations

from datetime import datetime


def normalize_datetime(value: str) -> str:
    parsed = datetime.fromisoformat(value)
    return parsed.strftime("%Y-%m-%dT%H:%M:%S")


def now_text() -> str:
    return datetime.now().replace(microsecond=0).isoformat()
