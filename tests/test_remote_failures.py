import pytest
import requests

from prompt_optimizer import repo_ops


class FailingResponse:
    def raise_for_status(self):
        raise requests.HTTPError("bad status")

    def json(self):
        return {}

    @property
    def text(self):
        return ""


def test_get_remote_last_commits_wraps_github_request_failures(monkeypatch):
    monkeypatch.setattr(
        repo_ops.requests, "get", lambda *args, **kwargs: FailingResponse()
    )

    with pytest.raises(RuntimeError, match="Failed to reach GitHub"):
        repo_ops.get_remote_last_commits("https://github.com/openai/openai-python")


def test_get_remote_commit_diff_wraps_gitlab_request_failures(monkeypatch):
    monkeypatch.setattr(
        repo_ops.requests, "get", lambda *args, **kwargs: FailingResponse()
    )

    with pytest.raises(RuntimeError, match="Failed to reach GitLab"):
        repo_ops.get_remote_commit_diff(
            "https://gitlab.com/group/subgroup/project",
            "abc1234",
        )
