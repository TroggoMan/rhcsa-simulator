"""
Tests that project docs don't reference removed/never-built features.

Regression coverage for issue #111: AI_SETUP.md documented an
"AI-powered feedback" system that was dropped in the v4.0.0 rewrite,
then came back into the docs via an accidental revert without the
code ever returning. Nothing in the codebase reads ANTHROPIC_API_KEY
or imports `anthropic` for end-user feedback (the repo-maintenance
GitHub Actions workflows are a separate, legitimate use of that env
var and are not covered by this check).
"""

from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

REPO_ROOT = Path(__file__).resolve().parents[2]


def test_ai_setup_doc_removed():
    assert not (REPO_ROOT / "AI_SETUP.md").exists(), (
        "AI_SETUP.md documents a feedback feature with no implementation "
        "in the codebase; see issue #111")


@pytest.mark.parametrize(
    "doc_name", ["README.md", "CLAUDE.md", "requirements.txt"])
def test_docs_do_not_reference_orphaned_ai_feedback(doc_name):
    text = (REPO_ROOT / doc_name).read_text().lower()
    assert "ai_setup.md" not in text
    assert "ai-powered feedback" not in text
    assert "ai feedback" not in text
    assert "anthropic>=" not in text
