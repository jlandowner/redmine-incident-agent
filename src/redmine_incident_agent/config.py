from __future__ import annotations

import os
from dataclasses import dataclass


def _required(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise RuntimeError(f"Environment variable {name} is required")
    return value


def _int(name: str, default: int) -> int:
    return int(os.getenv(name, str(default)))


def _float(name: str, default: float) -> float:
    return float(os.getenv(name, str(default)))


@dataclass(frozen=True)
class Settings:
    redmine_url: str
    redmine_api_key: str
    agent_instruction_page: str = "AgentInstruction"
    tag_write_field: str = "tag_list"
    normalized_tag: str = "agent:normalized"
    watermark_prefix: str = "agent:watermark="
    redmine_http_timeout: float = 20.0

    max_concurrency: int = 4
    project_limit: int = 100
    issue_limit: int = 100
    search_limit: int = 10

    llm_provider: str = "vllm"
    llm_model: str = ""
    llm_base_url: str | None = None
    llm_api_key: str | None = None

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            redmine_url=_required("REDMINE_URL").rstrip("/"),
            redmine_api_key=_required("REDMINE_API_KEY"),
            agent_instruction_page=os.getenv("REDMINE_AGENT_INSTRUCTION_PAGE", "AgentInstruction"),
            tag_write_field=os.getenv("REDMINE_TAG_WRITE_FIELD", "tag_list"),
            normalized_tag=os.getenv("REDMINE_NORMALIZED_TAG", "agent:normalized"),
            watermark_prefix=os.getenv("REDMINE_WATERMARK_PREFIX", "agent:watermark="),
            redmine_http_timeout=_float("REDMINE_HTTP_TIMEOUT", 20.0),
            max_concurrency=_int("MAX_CONCURRENCY", 4),
            project_limit=_int("PROJECT_LIMIT", 100),
            issue_limit=_int("ISSUE_LIMIT", 100),
            search_limit=_int("SEARCH_LIMIT", 10),
            llm_provider=os.getenv("LLM_PROVIDER", "vllm").strip(),
            llm_model=_required("LLM_MODEL"),
            llm_base_url=os.getenv("LLM_BASE_URL") or None,
            llm_api_key=os.getenv("LLM_API_KEY") or None,
        )
