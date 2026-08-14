"""
Tests for core.content - ContentRegistry loading and domain categories.
"""

import pytest
from core.content import ContentRegistry
from config import settings


pytestmark = pytest.mark.unit


class TestContentRegistry:
    """Test ContentRegistry initialization and queries."""

    def test_initializes_without_error(self):
        ContentRegistry._initialized = False
        ContentRegistry._content = {}
        ContentRegistry.initialize()
        assert ContentRegistry._initialized is True

    def test_all_domains_have_categories(self):
        """Every domain a version actually tests must have study content.

        Checked per version, because the domain set differs: v9 has a
        Containers domain that v10 dropped.
        """
        ContentRegistry.initialize()
        original = settings.get_exam_version()
        try:
            for version in settings.SUPPORTED_EXAM_VERSIONS:
                settings.set_exam_version(version)
                for domain_num in settings.exam_domains(version):
                    cats = ContentRegistry.get_categories_for_domain(domain_num)
                    assert len(cats) >= 1, (
                        f"v{version} domain {domain_num} has no categories")
        finally:
            settings.set_exam_version(original)

    def test_get_topic_returns_dict(self):
        ContentRegistry.initialize()
        topic = ContentRegistry.get_topic("lvm")
        assert topic is not None
        assert isinstance(topic, dict)
        assert "name" in topic
        assert "explanation" in topic
        assert "commands" in topic

    def test_get_topic_unknown_returns_none(self):
        ContentRegistry.initialize()
        topic = ContentRegistry.get_topic("nonexistent_category")
        assert topic is None

    def test_get_categories_for_domain_matches_settings(self):
        """Content categories must be reachable from their domain — for the
        version that actually tests them. A v9-only category like containers
        is legitimately absent from v10's domain list."""
        ContentRegistry.initialize()
        original = settings.get_exam_version()
        try:
            for version in settings.SUPPORTED_EXAM_VERSIONS:
                settings.set_exam_version(version)
                for cat, domain in settings.CATEGORY_TO_DOMAIN.items():
                    if not settings.category_in_scope(cat, version):
                        continue
                    domain_cats = ContentRegistry.get_categories_for_domain(domain)
                    # Not all settings categories may have content, but content
                    # categories should be a subset of settings
                    if cat in ContentRegistry.get_all_categories():
                        assert cat in domain_cats, (
                            f"v{version}: {cat} (domain {domain}) missing "
                            f"from ContentRegistry"
                        )
        finally:
            settings.set_exam_version(original)
