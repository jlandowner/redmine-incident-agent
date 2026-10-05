from __future__ import annotations

import logging
from datetime import datetime
from typing import Any
from urllib.parse import quote

import httpx

from .config import Settings
from .models import parse_datetime
from .state import extract_tags

log = logging.getLogger(__name__)


class RedmineError(RuntimeError):
    pass


class RedmineClient:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.client = httpx.AsyncClient(
            base_url=settings.redmine_url,
            timeout=settings.redmine_http_timeout,
            headers={
                "X-Redmine-API-Key": settings.redmine_api_key,
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
        )

    async def close(self) -> None:
        await self.client.aclose()

    async def _request(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        response = await self.client.request(method, path, **kwargs)
        if response.status_code >= 400:
            body = response.text[:2000]
            raise RedmineError(
                f"Redmine {method} {path} failed: {response.status_code}: {body}"
            )
        return response

    async def current_user_id(self) -> int:
        response = await self._request("GET", "/users/current.json")
        return int(response.json()["user"]["id"])

    async def list_projects(self) -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = []
        offset = 0
        while True:
            response = await self._request(
                "GET",
                "/projects.json",
                params={"limit": self.settings.project_limit, "offset": offset},
            )
            payload = response.json()
            batch = payload.get("projects", [])
            result.extend(batch)
            total = int(payload.get("total_count", len(result)))
            offset += len(batch)
            if not batch or offset >= total:
                return result

    async def get_agent_instruction(self, project_identifier: str) -> str | None:
        title = quote(self.settings.agent_instruction_page, safe="")
        path = f"/projects/{quote(project_identifier, safe='')}/wiki/{title}.json"
        response = await self.client.get(path)
        if response.status_code == 404:
            return None
        if response.status_code >= 400:
            raise RedmineError(
                f"Redmine GET {path} failed: {response.status_code}: {response.text[:2000]}"
            )
        page = response.json().get("wiki_page", {})
        return page.get("text") or ""

    async def list_open_issue_ids(self, project_id: int) -> list[int]:
        ids: list[int] = []
        offset = 0
        while True:
            response = await self._request(
                "GET",
                "/issues.json",
                params={
                    "project_id": project_id,
                    "status_id": "open",
                    "limit": self.settings.issue_limit,
                    "offset": offset,
                },
            )
            payload = response.json()
            batch = payload.get("issues", [])
            ids.extend(int(issue["id"]) for issue in batch)
            total = int(payload.get("total_count", len(ids)))
            offset += len(batch)
            if not batch or offset >= total:
                return ids

    async def get_issue(self, issue_id: int, *, include_journals: bool = False) -> dict[str, Any]:
        params = {"include": "journals"} if include_journals else None
        response = await self._request("GET", f"/issues/{issue_id}.json", params=params)
        return response.json()["issue"]

    async def update_issue(self, issue_id: int, **fields: Any) -> None:
        await self._request(
            "PUT",
            f"/issues/{issue_id}.json",
            json={"issue": fields},
        )

    async def update_title(self, issue_id: int, title: str) -> None:
        await self.update_issue(issue_id, subject=title)

    async def update_description(self, issue_id: int, description: str) -> None:
        await self.update_issue(issue_id, description=description)

    async def add_note(self, issue_id: int, message: str) -> None:
        await self.update_issue(issue_id, notes=message)

    async def set_tags(self, issue_id: int, tags: list[str]) -> None:
        """
        Write tags through the plugin-specific issue attribute.

        Default is `tag_list`, used by AlphaNodes additional_tags. If another
        plugin uses a different field, set REDMINE_TAG_WRITE_FIELD.
        """
        await self.update_issue(
            issue_id,
            **{self.settings.tag_write_field: sorted(set(tags))},
        )

    async def add_tag(self, issue_id: int, tag: str) -> None:
        # Re-read immediately before writing so unrelated human tags are preserved
        # as much as possible. Redmine tag plugins generally do not expose CAS.
        issue = await self.get_issue(issue_id)
        tags = extract_tags(issue)
        if tag in tags:
            return
        tags.append(tag)
        await self.set_tags(issue_id, tags)

    async def replace_tag_by_prefix(self, issue_id: int, prefix: str, new_tag: str) -> None:
        issue = await self.get_issue(issue_id)
        tags = [tag for tag in extract_tags(issue) if not tag.startswith(prefix)]
        tags.append(new_tag)
        await self.set_tags(issue_id, tags)

    async def search_issues(
        self,
        *,
        project_id: int,
        query: str,
        limit: int,
        status: str = "all",
        created_from: datetime | None = None,
        created_to: datetime | None = None,
        exclude_issue_id: int | None = None,
    ) -> list[dict[str, Any]]:
        """
        Use Redmine full-text Search API, then fetch candidate issues and apply
        project/status/time filters locally. This avoids relying on plugin/UI-only
        search filters and keeps Agent search semantics deterministic.
        """
        response = await self._request(
            "GET",
            "/search.json",
            params={
                "q": query,
                "issues": 1,
                "wiki_pages": 0,
                "news": 0,
                "documents": 0,
                "changesets": 0,
                "messages": 0,
                "projects": 0,
                "limit": min(max(limit * 3, limit), 100),
            },
        )
        search_results = response.json().get("results", [])

        results: list[dict[str, Any]] = []
        seen: set[int] = set()
        for item in search_results:
            item_type = str(item.get("type", ""))
            if not item_type.startswith("issue"):
                continue
            try:
                issue_id = int(item["id"])
            except (KeyError, TypeError, ValueError):
                continue
            if issue_id in seen or issue_id == exclude_issue_id:
                continue
            seen.add(issue_id)

            issue = await self.get_issue(issue_id)
            if int((issue.get("project") or {}).get("id", -1)) != project_id:
                continue

            is_closed = bool((issue.get("status") or {}).get("is_closed", False))
            if status == "open" and is_closed:
                continue
            if status == "closed" and not is_closed:
                continue

            created = parse_datetime(issue.get("created_on"))
            if created_from and (created is None or created < created_from):
                continue
            if created_to and (created is None or created > created_to):
                continue

            results.append(self.issue_for_agent(issue, include_description=True))
            if len(results) >= limit:
                break
        return results

    @staticmethod
    def issue_for_agent(
        issue: dict[str, Any], *, include_description: bool = True
    ) -> dict[str, Any]:
        data: dict[str, Any] = {
            "id": issue.get("id"),
            "project": issue.get("project"),
            "tracker": issue.get("tracker"),
            "status": issue.get("status"),
            "priority": issue.get("priority"),
            "subject": issue.get("subject"),
            "created_on": issue.get("created_on"),
            "updated_on": issue.get("updated_on"),
            "due_date": issue.get("due_date"),
            "assigned_to": issue.get("assigned_to"),
            "tags": extract_tags(issue),
            "custom_fields": issue.get("custom_fields", []),
        }
        if include_description:
            data["description"] = issue.get("description") or ""
        return data
