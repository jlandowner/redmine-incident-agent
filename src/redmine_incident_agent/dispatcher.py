from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass

from pydantic_ai import Agent

from .config import Settings
from .models import AgentDecision, AgentDeps
from .redmine import RedmineClient
from .state import (
    extract_tags,
    latest_external_journal_id,
    parse_watermark,
    should_process,
)

log = logging.getLogger(__name__)


@dataclass
class RunStats:
    projects_seen: int = 0
    projects_enabled: int = 0
    issues_seen: int = 0
    issues_run: int = 0
    issues_skipped: int = 0
    issues_failed: int = 0


class Dispatcher:
    def __init__(
        self,
        settings: Settings,
        redmine: RedmineClient,
        agent: Agent[AgentDeps, AgentDecision],
    ):
        self.settings = settings
        self.redmine = redmine
        self.agent = agent
        self.semaphore = asyncio.Semaphore(settings.max_concurrency)

    async def run_once(self) -> RunStats:
        stats = RunStats()
        agent_user_id = await self.redmine.current_user_id()
        projects = await self.redmine.list_projects()
        stats.projects_seen = len(projects)

        jobs: list[asyncio.Task[None]] = []
        for project in projects:
            project_identifier = project.get("identifier")
            if not project_identifier:
                continue

            instruction = await self.redmine.get_agent_instruction(project_identifier)
            if instruction is None:
                continue
            stats.projects_enabled += 1

            issue_ids = await self.redmine.list_open_issue_ids(int(project["id"]))
            stats.issues_seen += len(issue_ids)
            for issue_id in issue_ids:
                jobs.append(
                    asyncio.create_task(
                        self._process_issue(
                            stats=stats,
                            project_id=int(project["id"]),
                            project_identifier=project_identifier,
                            issue_id=issue_id,
                            instruction=instruction,
                            agent_user_id=agent_user_id,
                        )
                    )
                )

        if jobs:
            await asyncio.gather(*jobs)
        return stats

    async def _process_issue(
        self,
        *,
        stats: RunStats,
        project_id: int,
        project_identifier: str,
        issue_id: int,
        instruction: str,
        agent_user_id: int,
    ) -> None:
        async with self.semaphore:
            try:
                issue = await self.redmine.get_issue(issue_id, include_journals=True)
                tags = extract_tags(issue)
                journals = list(issue.get("journals", []))

                normalized = self.settings.normalized_tag in tags
                stored_watermark = parse_watermark(tags, self.settings.watermark_prefix)

                # Snapshot at the START of the run. Never advance to a Journal
                # that may arrive while the Agent is running.
                input_watermark = latest_external_journal_id(journals, agent_user_id)

                if not should_process(
                    normalized=normalized,
                    stored_watermark=stored_watermark,
                    input_watermark=input_watermark,
                ):
                    stats.issues_skipped += 1
                    return

                normalization_required = not normalized
                next_action_allowed = (
                    stored_watermark is None or input_watermark > stored_watermark
                )

                deps = AgentDeps(
                    redmine=self.redmine,
                    project_id=project_id,
                    project_identifier=project_identifier,
                    issue_id=issue_id,
                    agent_instruction=instruction,
                    agent_user_id=agent_user_id,
                    issue_snapshot=issue,
                    journal_snapshot=journals,
                    input_watermark=input_watermark,
                    normalization_required=normalization_required,
                    next_action_allowed=next_action_allowed,
                    original_description=issue.get("description") or "",
                )

                result = await self.agent.run(
                    "現在のRedmine Issueを設計された手順1〜6に従って処理してください。",
                    deps=deps,
                )
                decision = result.output

                if normalization_required and not deps.state.normalization_complete:
                    raise RuntimeError(
                        "Agent did not complete both title/description normalization"
                    )

                if decision.next_action_required and not deps.state.note_added:
                    raise RuntimeError(
                        "Agent declared next_action_required=true but did not call add_note"
                    )

                # Mark exactly the external input snapshot that was actually
                # available at run start. A later human/monitor update therefore
                # remains > watermark and is processed on the next Cron run.
                await self.redmine.replace_tag_by_prefix(
                    issue_id,
                    self.settings.watermark_prefix,
                    f"{self.settings.watermark_prefix}{input_watermark}",
                )

                stats.issues_run += 1
                log.info(
                    "issue=%s processed normalized=%s watermark=%s next_action=%s summary=%s",
                    issue_id,
                    normalization_required,
                    input_watermark,
                    deps.state.note_added,
                    decision.summary,
                )
            except Exception:
                stats.issues_failed += 1
                log.exception("issue=%s processing failed", issue_id)
