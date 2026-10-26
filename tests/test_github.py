import json

import pytest

from benchwatch.github import MARKER, GitHub, GitHubError, prepare_comment, publish

HEAD = "a" * 40


class FakeApi:
    """Records requests and serves canned responses keyed by (method, path prefix)."""

    def __init__(self, comments=None, pr_head=HEAD):
        self.calls = []
        self.comments = comments or []
        self.pr_head = pr_head

    def __call__(self, method, url, body):
        path = url.split("/repos/o/r/", 1)[1]
        self.calls.append((method, path, body))
        if method == "GET" and path.startswith("pulls/"):
            return {"head": {"sha": self.pr_head}}
        if method == "GET" and "comments" in path:
            page = int(path.rsplit("page=", 1)[1])
            return self.comments[(page - 1) * 100: page * 100]
        return {}

    def writes(self):
        return [(m, p, b) for m, p, b in self.calls if m != "GET"]


def write_artifact(tmp_path, regressions=0, head_sha=HEAD, number=7):
    (tmp_path / "pr.json").write_text(json.dumps({"number": number, "head_sha": head_sha}))
    (tmp_path / "results.json").write_text(json.dumps({
        "summary": {"regression": regressions, "unchanged": 3},
        "status_description": f"{regressions} regressions",
    }))
    (tmp_path / "comment.md").write_text(f"{MARKER}\n### Benchwatch\nbody")
    return tmp_path


def test_creates_comment_and_success_status(tmp_path):
    api = FakeApi()
    msg = publish(GitHub("o/r", api), HEAD, "success", write_artifact(tmp_path), "https://run")
    assert "created" in msg
    (m1, p1, b1), (m2, p2, b2) = api.writes()
    assert (m1, p1) == ("POST", "issues/7/comments")
    assert b1["body"].startswith(MARKER)
    assert b1["body"].count(MARKER) == 1
    assert (m2, p2) == ("POST", f"statuses/{HEAD}")
    assert b2 == {"state": "success", "context": "benchwatch", "description": "0 regressions",
                  "target_url": "https://run"}


def test_updates_existing_comment_found_on_later_page(tmp_path):
    comments = [{"id": i, "body": "unrelated"} for i in range(100)] + [{"id": 555, "body": f"{MARKER}\nold"}]
    api = FakeApi(comments=comments)
    publish(GitHub("o/r", api), HEAD, "success", write_artifact(tmp_path, regressions=2))
    (m1, p1, _), (_, _, status) = api.writes()
    assert (m1, p1) == ("PATCH", "issues/comments/555")
    assert status["state"] == "failure"


def test_failed_run_sets_error_status_without_commenting(tmp_path):
    api = FakeApi()
    publish(GitHub("o/r", api), HEAD, "failure", tmp_path)
    [(method, path, body)] = api.writes()
    assert path == f"statuses/{HEAD}"
    assert body["state"] == "error"


def test_cancelled_run_does_nothing(tmp_path):
    api = FakeApi()
    publish(GitHub("o/r", api), HEAD, "cancelled", write_artifact(tmp_path))
    assert api.calls == []


def test_artifact_claiming_other_head_is_rejected(tmp_path):
    api = FakeApi()
    with pytest.raises(GitHubError):
        publish(GitHub("o/r", api), HEAD, "success", write_artifact(tmp_path, head_sha="b" * 40))
    assert api.writes() == []


def test_pr_that_moved_on_is_skipped(tmp_path):
    api = FakeApi(pr_head="c" * 40)
    msg = publish(GitHub("o/r", api), HEAD, "success", write_artifact(tmp_path))
    assert "skipping" in msg
    assert api.writes() == []


def test_prepare_comment_truncates_and_keeps_single_marker():
    body = prepare_comment(f"{MARKER}{MARKER}" + "x" * 100_000)
    assert body.count(MARKER) == 1
    assert len(body) < 65_536
    assert body.rstrip().endswith("(truncated)")
