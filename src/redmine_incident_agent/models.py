from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class AgentDecision(BaseModel):
    summary: str = Field(description="今回の解析結果の短い要約")
    next_action_required: bool = Field(
        description="人間に追加調査を依頼するNext Actionが必要ならtrue"
    )


@dataclass
class RunState:
    title_updated: bool = False
    description_updated: bool = False
    normalized_tag_written: bool = False
    note_added: bool = False

    @property
    def normalization_complete(self) -> bool:
        return self.title_updated and self.description_updated and self.normalized_tag_written


@dataclass
class AgentDeps:
    redmine: Any
    project_id: int
    project_identifier: str
    issue_id: int
    agent_instruction: str
    agent_user_id: int

    issue_snapshot: dict[str, Any]
    journal_snapshot: list[dict[str, Any]]
    input_watermark: int
    normalization_required: bool
    next_action_allowed: bool

    original_description: str
    state: RunState = field(default_factory=RunState)


def parse_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    value = value.replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None
