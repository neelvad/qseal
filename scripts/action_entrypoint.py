"""GitHub Action entrypoint: scan changed dbt models and comment on the PR.

Deterministic tier only - the builtin rule scanner needs no external solvers.
Reads configuration from INPUT_* environment variables (set by action.yml) and
the standard GITHUB_* variables. Posts or idempotently updates a single PR
comment, and fails the check when configured.
"""

import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

from snowprove.dbt.git_diff import GitDiffError, changed_model_paths
from snowprove.dbt.scan import scan_dbt_project
from snowprove.report.markdown import COMMENT_MARKER, render_dbt_scan_markdown
from snowprove.rewrites.registry import DEFAULT_RULES

API = "https://api.github.com"


def main() -> int:
    project = Path(os.environ.get("INPUT_PROJECT", ".")).resolve()
    base_ref = os.environ.get("INPUT_BASE_REF", "").strip()
    fail_on = os.environ.get("INPUT_FAIL_ON", "none").strip()
    comment = os.environ.get("INPUT_COMMENT", "true").strip().lower() == "true"
    dialect = os.environ.get("INPUT_DIALECT", "snowflake").strip()

    only_paths = None
    if base_ref:
        try:
            only_paths = changed_model_paths(project, base_ref)
        except GitDiffError as error:
            print(f"snowprove: {error}", file=sys.stderr)
            return 2
        if not only_paths:
            print("snowprove: no changed dbt models; nothing to scan.")
            return 0

    result = scan_dbt_project(
        project, rules=DEFAULT_RULES, dialect=dialect, only_paths=only_paths
    )
    markdown = render_dbt_scan_markdown(result)
    findings = result.proven_finding_count()
    print(markdown)

    if comment:
        try:
            _post_pr_comment(markdown)
        except urllib.error.HTTPError as error:  # noqa: BLE001 - never fail the job on comment errors
            print(f"snowprove: could not post PR comment ({error.code}).", file=sys.stderr)

    if fail_on == "findings" and findings > 0:
        return 1
    return 0


def _post_pr_comment(body: str) -> None:
    token = os.environ.get("GITHUB_TOKEN")
    repo = os.environ.get("GITHUB_REPOSITORY")
    pr_number = _pr_number()
    if not (token and repo and pr_number):
        print("snowprove: not a PR context or missing token; skipping comment.", file=sys.stderr)
        return

    base = f"{API}/repos/{repo}/issues/{pr_number}/comments"
    existing = _request("GET", base, token)
    comment_id = find_comment_id(existing, COMMENT_MARKER)
    if comment_id is not None:
        _request("PATCH", f"{API}/repos/{repo}/issues/comments/{comment_id}", token,
                 {"body": body})
    else:
        _request("POST", base, token, {"body": body})


def find_comment_id(comments: list[dict], marker: str) -> int | None:
    """ID of the first comment containing the marker, for idempotent updates."""
    for comment in comments:
        if marker in (comment.get("body") or ""):
            return comment.get("id")
    return None


def _pr_number() -> int | None:
    event_path = os.environ.get("GITHUB_EVENT_PATH")
    if event_path and Path(event_path).exists():
        event = json.loads(Path(event_path).read_text())
        pull_request = event.get("pull_request")
        if pull_request and "number" in pull_request:
            return int(pull_request["number"])
    return None


def _request(method: str, url: str, token: str, payload: dict | None = None):
    data = json.dumps(payload).encode() if payload is not None else None
    request = urllib.request.Request(url, data=data, method=method)
    request.add_header("Authorization", f"Bearer {token}")
    request.add_header("Accept", "application/vnd.github+json")
    if data is not None:
        request.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(request) as response:  # noqa: S310 - fixed api.github.com host
        return json.loads(response.read() or "null")


if __name__ == "__main__":
    sys.exit(main())
