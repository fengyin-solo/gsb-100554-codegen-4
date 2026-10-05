"""保险理赔领域错误。"""
from __future__ import annotations


class DomainError(Exception):
    """可直接返回给调用方的业务错误。"""

    status_code = 400


class ValidationFailed(DomainError):
    status_code = 422


class NotFound(DomainError):
    status_code = 404


class Conflict(DomainError):
    status_code = 409
