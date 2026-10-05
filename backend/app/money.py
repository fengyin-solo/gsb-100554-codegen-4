"""金额单位转换：数据库统一以“分”保存，避免浮点误差。"""
from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal

CENT = Decimal("100")


def to_cents(amount: Decimal | int | float) -> int:
    return int(Decimal(str(amount)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP) * CENT)


def from_cents(cents: int | None) -> float:
    if cents is None:
        return 0.0
    return float((Decimal(cents) / CENT).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))
