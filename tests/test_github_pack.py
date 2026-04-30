"""Validate the github pack against its fixtures.

This is the taskboard contract test: a pack is valid iff probe() produces
well-formed Status for every fixture.
"""
from pathlib import Path

import pytest

from taskboard.contract import Context, Status
from taskboard.packs.github import pack

FIXTURES = Path(__file__).parent.parent / "taskboard" / "packs" / "github" / "fixtures"


def _ctx():
    return Context(fixtures_dir=str(FIXTURES))


def test_probe_repo_populates_facts_and_details():
    status = pack.probe("gh/repo", "softwaresoftware-dev/softwaresoftware-plugins", _ctx())
    assert isinstance(status, Status)
    assert status.facts["open_issues"] == 0
    assert status.facts["archived"] is False
    assert status.facts["private"] is False
    assert isinstance(status.facts["pushed_days_ago"], int)
    assert status.details["default_branch"] == "main"
    assert status.details["name"] == "softwaresoftware-dev/softwaresoftware-plugins"


def test_probe_pull_requests_empty():
    status = pack.probe("gh/pull-requests", "any/any", _ctx())
    assert status.facts["count"] == 0
    assert status.facts["oldest_age_days"] is None
    assert status.details["prs"] == []


def test_probe_releases_empty():
    status = pack.probe("gh/releases", "any/any", _ctx())
    assert status.facts["count"] == 0
    assert status.facts["latest_age_days"] is None
    assert status.details["latest_tag"] is None


def test_unknown_kind_raises():
    with pytest.raises(ValueError):
        pack.probe("gh/nonexistent", "any/any", _ctx())


def test_missing_fixtures_dir_raises():
    with pytest.raises(NotImplementedError):
        pack.probe("gh/repo", "any/any", Context())
