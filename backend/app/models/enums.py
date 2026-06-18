"""Domain enums shared by the ORM tables and the Pydantic DTOs.

Kept in a neutral module so the SQL layer and the schema layer can both import
them without depending on each other.
"""

from __future__ import annotations

import enum


class JobStatus(str, enum.Enum):
    """Lifecycle status of a job posting (see Data_Models.md)."""

    NEW = "NEW"
    MATCHED = "MATCHED"
    REJECTED_BY_AI = "REJECTED_BY_AI"
