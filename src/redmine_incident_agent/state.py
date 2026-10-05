from __future__ import annotations

from typing import Any, Iterable


def extract_tags(issue: dict[str, Any]) -> list[str]:
    """Normalize tag formats used by common Redmine tag plugins."""
    raw = issue.get("tags")
    if raw is None:
        raw = issue.get("tag_list")
    if raw is None:
        return []

    if isinstance(raw, str):
        return [x.strip() for x in raw.replace(",", " ").split() if x.strip()]

    tags: list[str] = []
    if isinstance(raw, list):
        for item in raw:
            if isinstance(item, str):
                if item.strip():
                    tags.append(item.strip())
            elif isinstance(item, dict):
                name = item.get("name") or item.get("tag")
                if isinstance(name, str) and name.strip():
                    tags.append(name.strip())
    return tags


def parse_watermark(tags: Iterable[str], prefix: str) -> int | None:
    best: int | None = None
    for tag in tags:
        if not tag.startswith(prefix):
            continue
        raw = tag[len(prefix) :]
        try:
            value = int(raw)
        except ValueError:
            continue
        best = value if best is None else max(best, value)
    return best


def latest_external_journal_id(
    journals: Iterable[dict[str, Any]], agent_user_id: int
) -> int:
    latest = 0
    for journal in journals:
        user = journal.get("user") or {}
        user_id = user.get("id")
        if user_id == agent_user_id:
            continue
        try:
            journal_id = int(journal.get("id", 0))
        except (TypeError, ValueError):
            continue
        latest = max(latest, journal_id)
    return latest


def should_process(
    *, normalized: bool, stored_watermark: int | None, input_watermark: int
) -> bool:
    if not normalized:
        return True
    if stored_watermark is None:
        return True
    return input_watermark > stored_watermark
