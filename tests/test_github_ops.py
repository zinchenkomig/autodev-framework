"""Unit tests for autodev.core.github_ops."""

from autodev.core.github_ops import extract_pr_info


def test_extract_pr_info_valid():
    result = extract_pr_info("https://github.com/zinchenkomig/my-repo/pull/42")
    assert result == ("my-repo", 42)


def test_extract_pr_info_different_org():
    result = extract_pr_info("https://github.com/someorg/another-repo/pull/123")
    assert result == ("another-repo", 123)


def test_extract_pr_info_pr_number_1():
    result = extract_pr_info("https://github.com/org/repo/pull/1")
    assert result == ("repo", 1)


def test_extract_pr_info_invalid_no_pull():
    result = extract_pr_info("https://github.com/org/repo/issues/10")
    assert result is None


def test_extract_pr_info_invalid_empty():
    result = extract_pr_info("")
    assert result is None


def test_extract_pr_info_invalid_random_string():
    result = extract_pr_info("not-a-url")
    assert result is None


def test_extract_pr_info_missing_pr_number():
    result = extract_pr_info("https://github.com/org/repo/pull/")
    assert result is None


def test_extract_pr_info_repo_with_hyphens():
    result = extract_pr_info("https://github.com/zinchenkomig/great-alerter-backend/pull/7")
    assert result == ("great-alerter-backend", 7)
