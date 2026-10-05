"""保险理赔与财务待收款接口模型。"""
from __future__ import annotations

from decimal import Decimal

from pydantic import BaseModel, Field, field_validator


class ClaimCreate(BaseModel):
    """新增出险报案；保单免赔额和赔付上限在建档时固化。"""

    case_no: str = Field(description="案件编号")
    occurred_at: str = Field(description="出险时间，格式 YYYY-MM-DDTHH:MM:SS")
    reported_at: str = Field(description="报案时间，格式 YYYY-MM-DDTHH:MM:SS")
    damaged_equipment: str = Field(description="受损设备")
    estimated_loss: Decimal = Field(ge=0, description="估损金额")
    deductible: Decimal = Field(ge=0, description="保单免赔额")
    payout_cap: Decimal = Field(ge=0, description="保单赔付上限")
    policy_no: str | None = Field(default=None, description="保单号")
    policy_version: str = Field(default="2026版", description="适用保单条款")
    remark: str | None = None

    @field_validator("case_no", "occurred_at", "reported_at", "damaged_equipment", "policy_version")
    @classmethod
    def required_text(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("不能为空")
        return value


class ClaimBackfill(BaseModel):
    """存量案件回填；是否结案、最终赔付与原有条款按回填值保留。"""

    case_no: str = Field(description="案件编号")
    occurred_at: str = Field(description="出险时间")
    reported_at: str | None = Field(default=None, description="报案时间；历史资料缺失时可留空")
    damaged_equipment: str = Field(description="受损设备")
    estimated_loss: Decimal = Field(ge=0, description="估损金额")
    deductible: Decimal = Field(ge=0, description="原保单免赔额")
    payout_cap: Decimal = Field(ge=0, description="原保单赔付上限")
    policy_no: str | None = None
    policy_version: str = Field(description="原保单条款版本")
    assessment_no: str | None = Field(default=None, description="原定损单号")
    assessment_basis: str | None = Field(default=None, description="原定损口径")
    assessed_loss: Decimal | None = Field(default=None, ge=0, description="原定损金额")
    payout_rule: str | None = Field(default=None, description="原从严规则：免赔额或赔付上限")
    status: str | None = Field(default=None, description="已报案、已定损或已结案")
    closed_at: str | None = Field(default=None, description="原结案时间")
    closed: bool | None = Field(default=None, description="是否已结案")
    received: bool | None = Field(default=None, description="已结案款项是否已到账")
    remark: str | None = None

    @field_validator(
        "case_no",
        "occurred_at",
        "damaged_equipment",
        "policy_version",
    )
    @classmethod
    def required_text(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("不能为空")
        return value

    @field_validator("reported_at", "policy_no", "assessment_no", "assessment_basis", "payout_rule", "status", "closed_at", "remark")
    @classmethod
    def blank_to_none(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        return value or None


class AssessmentSubmit(BaseModel):
    """定损单提交内容。同一定损单号只接收第一次提交。"""

    assessment_no: str = Field(description="定损单号")
    assessment_basis: str = Field(description="定损口径")
    assessed_loss: Decimal = Field(ge=0, description="定损金额")

    @field_validator("assessment_no", "assessment_basis")
    @classmethod
    def required_text(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("不能为空")
        return value


class ReceivableConfirm(BaseModel):
    """财务确认保险赔款到账。"""

    received_at: str | None = Field(default=None, description="到账时间，默认由服务端生成")

    @field_validator("received_at")
    @classmethod
    def blank_to_none(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        return value or None
