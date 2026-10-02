"""Contracts for the first controlled multi-agent generation pipeline."""

from enum import StrEnum


class AgentRole(StrEnum):
    CASE_WRITER = "case_writer"
    QUALITY_REVIEWER = "quality_reviewer"


class MergeDisposition(StrEnum):
    SELECTED = "selected"
    MERGED = "merged"
    MERGED_DUPLICATE = "merged_duplicate"
    REJECTED = "rejected"
