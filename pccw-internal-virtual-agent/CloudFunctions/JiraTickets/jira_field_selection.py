"""Project-aware Jira request fields, shared by incremental and repair jobs."""

import json
import logging
import os
from collections.abc import Iterator
from datetime import datetime, timezone
from pathlib import Path


TICKET_FIELDS = (
    "key", "issuetype", "project", "summary", "status", "created", "updated",
    "resolutiondate", "duedate", "creator", "reporter", "assignee", "components",
    "priority", "resolution", "issuelinks", "description", "labels", "attachment",
    "timetracking", "timespent",
    "customfield_10088", "customfield_10347", "customfield_10382",
    "customfield_10514", "customfield_10515", "customfield_10516",
    "customfield_10552", "customfield_10560", "customfield_10625",
    "customfield_10627", "customfield_10640", "customfield_10647",
    "customfield_10666", "customfield_10668", "customfield_10674",
    "customfield_10686", "customfield_10775", "customfield_10780",
    "customfield_11134", "customfield_11170", "customfield_11171",
    "customfield_11184", "customfield_11349", "customfield_11350",
    "customfield_11351", "customfield_11365", "customfield_12378",
    "customfield_13448", "customfield_13449", "customfield_13450",
    "customfield_15295", "customfield_15761", "customfield_15827",
    "customfield_15829",
)


class JiraFieldSelector:
    def __init__(
        self,
        profile_path: Path | None = None,
        enabled: bool | None = None,
        now: datetime | None = None,
    ) -> None:
        flag = os.environ.get("ENABLE_PROJECT_FIELD_SELECTION", "false").strip().lower()
        if enabled is None and flag not in {"true", "false"}:
            raise ValueError("ENABLE_PROJECT_FIELD_SELECTION must be true or false")
        self.enabled = flag == "true" if enabled is None else enabled
        self._projects: dict[str, frozenset[str]] = {}
        self._aliases: dict[str, str] = {}
        self._warned: set[str] = set()
        self._logged: set[str] = set()
        if not self.enabled:
            logging.info("[JIRA_FIELDS] Project field selection disabled")
            return

        path = profile_path or Path(__file__).with_name("jira_field_profiles.json")
        try:
            with path.open(encoding="utf-8") as stream:
                profile = json.load(stream)
        except FileNotFoundError:
            logging.warning("[JIRA_FIELDS] Profile missing; retaining all ticket fields")
            return
        if not isinstance(profile, dict) or profile.get("version") != 1:
            raise ValueError("Unsupported Jira field profile version")
        if profile.get("jira_site") != "consoleconnect.atlassian.net":
            raise ValueError("Jira field profile belongs to a different site")
        try:
            expires_at = datetime.fromisoformat(profile["expires_at"].replace("Z", "+00:00"))
        except (KeyError, AttributeError, ValueError) as exc:
            raise ValueError("Jira field profile needs a valid expires_at") from exc
        if expires_at.tzinfo is None:
            raise ValueError("Jira field profile expires_at must include a timezone")
        if (now or datetime.now(timezone.utc)) >= expires_at:
            logging.warning("[JIRA_FIELDS] Profile expired; retaining all ticket fields")
            return

        audited = profile.get("audited_custom_fields")
        projects = profile.get("projects")
        if (
            not isinstance(audited, list)
            or not audited
            or any(not isinstance(field, str) or not field.startswith("customfield_") for field in audited)
            or len(set(audited)) != len(audited)
            or not isinstance(projects, list)
        ):
            raise ValueError("Invalid Jira field profile fields or projects")
        for project in projects:
            if not isinstance(project, dict):
                raise ValueError("Invalid Jira field profile project")
            project_id = project.get("id")
            key = project.get("key")
            aliases = project.get("names")
            excluded = project.get("excluded_custom_fields")
            if (
                not isinstance(project_id, str) or not project_id.isdigit()
                or not isinstance(key, str) or not key
                or not isinstance(aliases, list)
                or any(not isinstance(alias, str) or not alias for alias in aliases)
                or not isinstance(excluded, list)
                or any(not isinstance(field, str) or field not in audited for field in excluded)
                or project_id in self._projects
            ):
                raise ValueError("Invalid Jira field profile project scope")
            self._projects[project_id] = frozenset(excluded)
            for alias in [project_id, key, *aliases]:
                normalized = alias.casefold()
                if normalized in self._aliases and self._aliases[normalized] != project_id:
                    raise ValueError(f"Ambiguous Jira project alias: {alias}")
                self._aliases[normalized] = project_id
        logging.info("[JIRA_FIELDS] Loaded verified scopes for %s projects", len(self._projects))

    def select(self, fields: list[str] | tuple[str, ...], project: str | None) -> list[str]:
        if not self.enabled or not self._projects:
            return list(fields)
        project_id = self._aliases.get(str(project).casefold())
        if project_id is None:
            label = str(project)
            if label not in self._warned:
                logging.warning("[JIRA_FIELDS] Unknown project %s; retaining all ticket fields", label)
                self._warned.add(label)
            return list(fields)
        excluded = self._projects[project_id]
        selected = [field for field in fields if field not in excluded]
        if project_id not in self._logged:
            logging.info(
                "[JIRA_FIELDS] project=%s requested=%s custom=%s excluded=%s",
                project_id, len(selected),
                sum(field.startswith("customfield_") for field in selected),
                len(fields) - len(selected),
            )
            self._logged.add(project_id)
        return selected

    def select_for_key(self, fields: list[str] | tuple[str, ...], key: str) -> list[str]:
        prefix, separator, number = key.rpartition("-")
        return self.select(fields, prefix if separator and number.isdigit() else None)

    def batches(
        self, keys: list[str], fields: list[str] | tuple[str, ...], size: int = 50
    ) -> Iterator[tuple[list[str], list[str]]]:
        if size <= 0:
            raise ValueError("Jira batch size must be positive")
        groups: dict[tuple[str, ...], list[str]] = {}
        for key in keys:
            if not key:
                continue
            selected = tuple(self.select_for_key(fields, key))
            groups.setdefault(selected, []).append(key)
        for selected, group in groups.items():
            for start in range(0, len(group), size):
                yield group[start:start + size], list(selected)

    def needs_full_fetch(self, issue: dict, requested: list[str], fields: tuple[str, ...] | list[str]) -> bool:
        if not self.enabled:
            return False
        project = issue.get("fields", {}).get("project") or {}
        project_id = project.get("id")
        required = self.select(fields, project_id)
        return not set(required).issubset(requested)


def fetch_issue_with_fields(
    session,
    url: str,
    headers: dict,
    auth: tuple,
    selector: JiraFieldSelector,
    project: str | None,
) -> dict:
    kwargs = {"headers": headers, "auth": auth, "timeout": 30}
    selected = selector.select(TICKET_FIELDS, project)
    if selector.enabled:
        kwargs["params"] = {"fields": ",".join(selected)}
    response = session.get(url, **kwargs)
    response.raise_for_status()
    issue = response.json()
    if selector.enabled and selector.needs_full_fetch(issue, selected, TICKET_FIELDS):
        logging.warning("[JIRA_FIELDS] Project changed for %s; fetching all ticket fields", issue.get("key"))
        kwargs["params"] = {"fields": ",".join(TICKET_FIELDS)}
        response = session.get(url, **kwargs)
        response.raise_for_status()
        issue = response.json()
    return issue
