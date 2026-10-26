"""Post the PR comment and commit status through the GitHub REST API.

This runs in the privileged `workflow_run` job, so everything read from the
benchmark artifact is treated as untrusted: the PR number is checked against
the head SHA that GitHub itself reported for the run, and the comment body is
size-capped and always carries our own marker.
"""

import json
import os
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from benchwatch.report import MARKER

API_URL = "https://api.github.com"
STATUS_CONTEXT = "benchwatch"
MAX_COMMENT_CHARS = 60_000  # GitHub's limit is 65,536

# (method, url, json body or None) -> parsed JSON response
Transport = Callable[[str, str, dict | None], object]


class GitHubError(RuntimeError):
    pass


def urllib_transport(token: str) -> Transport:
    def send(method: str, url: str, body: dict | None) -> object:
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(url, data=data, method=method, headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "benchwatch",
        })
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                payload = resp.read()
        except urllib.error.HTTPError as e:
            raise GitHubError(f"{method} {url} -> {e.code}: {e.read().decode(errors='replace')[:500]}") from e
        return json.loads(payload) if payload else None
    return send


@dataclass
class GitHub:
    repo: str  # "owner/name"
    send: Transport
    api_url: str = API_URL

    def _url(self, path: str) -> str:
        return f"{self.api_url}/repos/{self.repo}/{path}"

    def get_pull(self, number: int) -> dict:
        return self.send("GET", self._url(f"pulls/{number}"), None)

    def find_comment(self, pr: int) -> dict | None:
        page = 1
        while True:
            batch = self.send("GET", self._url(f"issues/{pr}/comments?per_page=100&page={page}"), None)
            for comment in batch:
                if MARKER in comment.get("body", ""):
                    return comment
            if len(batch) < 100:
                return None
            page += 1

    def upsert_comment(self, pr: int, body: str) -> str:
        existing = self.find_comment(pr)
        if existing:
            self.send("PATCH", self._url(f"issues/comments/{existing['id']}"), {"body": body})
            return "updated"
        self.send("POST", self._url(f"issues/{pr}/comments"), {"body": body})
        return "created"

    def set_status(self, sha: str, state: str, description: str, target_url: str | None = None) -> None:
        body = {"state": state, "context": STATUS_CONTEXT, "description": description[:140]}
        if target_url:
            body["target_url"] = target_url
        self.send("POST", self._url(f"statuses/{sha}"), body)


def prepare_comment(body: str) -> str:
    body = body.replace(MARKER, "").strip()
    if len(body) > MAX_COMMENT_CHARS:
        body = body[:MAX_COMMENT_CHARS] + "\n\n…(truncated)"
    return f"{MARKER}\n{body}\n"


def publish(
    gh: GitHub,
    head_sha: str,
    conclusion: str,
    artifact_dir: Path,
    target_url: str | None = None,
) -> str:
    """Post comment + status for a finished benchmark run. Returns a log line."""
    if conclusion in ("cancelled", "skipped"):
        return f"run {conclusion}; leaving status for the newer run"

    pr_file, results_file, comment_file = (artifact_dir / n for n in ("pr.json", "results.json", "comment.md"))
    if conclusion != "success" or not results_file.exists():
        gh.set_status(head_sha, "error", "Benchmark run failed; see the workflow log", target_url)
        return f"run concluded '{conclusion}' without results; status set to error"

    pr = json.loads(pr_file.read_text(encoding="utf-8"))
    number = int(pr["number"])
    if pr.get("head_sha") != head_sha:
        raise GitHubError(f"artifact claims head {pr.get('head_sha')} but the run was for {head_sha}; "
                          "refusing to publish")
    actual_head = gh.get_pull(number)["head"]["sha"]
    if actual_head != head_sha:
        # Either the artifact names the wrong PR, or the PR got new commits
        # since this run started. Either way this comment would be wrong.
        return f"PR #{number} head is now {actual_head[:7]}, not {head_sha[:7]}; skipping"

    results = json.loads(results_file.read_text(encoding="utf-8"))
    action = gh.upsert_comment(number, prepare_comment(comment_file.read_text(encoding="utf-8")))
    state = "failure" if results["summary"].get("regression", 0) else "success"
    gh.set_status(head_sha, state, results.get("status_description", state), target_url)
    return f"comment {action} on PR #{number}; status {state}"


def from_env(repo: str | None) -> GitHub:
    token = os.environ.get("GITHUB_TOKEN")
    repo = repo or os.environ.get("GITHUB_REPOSITORY")
    if not token or not repo:
        raise GitHubError("GITHUB_TOKEN and --repo (or GITHUB_REPOSITORY) are required")
    return GitHub(repo=repo, send=urllib_transport(token))
