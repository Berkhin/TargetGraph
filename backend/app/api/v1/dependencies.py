"""FastAPI dependency helpers for common patterns."""

from __future__ import annotations

from fastapi import HTTPException, status
from typing import TypeVar, Generic

T = TypeVar("T")


def require_resource(resource: T | None, detail: str) -> T:
    """Raise HTTP 404 if resource is None; otherwise return it.

    Usage in endpoints:
        job = await repo.get_by_id(job_id)
        job = require_resource(job, "job posting not found")
    """
    if resource is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=detail)
    return resource
