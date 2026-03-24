import pytest

from prompt_optimizer.repo_ops import parse_remote_repo_url


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        (
            "https://github.com/openai/openai-python",
            ("github", "openai", "openai-python"),
        ),
        (
            "https://github.com/openai/openai-python.git",
            ("github", "openai", "openai-python"),
        ),
        (
            "https://gitlab.com/group/subgroup/project",
            ("gitlab", "group/subgroup", "project"),
        ),
    ],
)
def test_parse_remote_repo_url(url, expected):
    assert parse_remote_repo_url(url) == expected


def test_parse_remote_repo_url_invalid():
    with pytest.raises(RuntimeError):
        parse_remote_repo_url("https://example.com/not-supported/repo")
