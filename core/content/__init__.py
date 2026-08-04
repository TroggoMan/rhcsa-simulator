"""
Content Registry for RHCSA Simulator v4.0.0
Loads domain-based learning content modules aligned with EX200 v10 exam objectives.
"""

import importlib
import logging

logger = logging.getLogger(__name__)

# Domain module mapping
_DOMAIN_MODULES = {
    1: "core.content.domain_1_software",
    2: "core.content.domain_2_boot",
    3: "core.content.domain_3_users",
    4: "core.content.domain_4_storage",
    5: "core.content.domain_5_networking",
    6: "core.content.domain_6_services",
    7: "core.content.domain_7_security",
    8: "core.content.domain_8_automation",
    9: "core.content.domain_9_containers",
}


class ContentRegistry:
    """Central registry for all learning content, organized by exam domain."""

    _content = {}
    _initialized = False

    @classmethod
    def initialize(cls):
        """Load all domain content modules."""
        if cls._initialized:
            return

        for domain_num, module_path in _DOMAIN_MODULES.items():
            try:
                mod = importlib.import_module(module_path)
                content = getattr(mod, "CONTENT", {})
                cls._content.update(content)
                logger.debug(
                    f"Loaded domain {domain_num}: {len(content)} categories"
                )
            except ImportError as e:
                logger.warning(f"Could not load {module_path}: {e}")
            except Exception as e:
                logger.error(f"Error loading {module_path}: {e}")

        cls._initialized = True
        logger.info(
            f"ContentRegistry initialized: {len(cls._content)} categories"
        )

    @classmethod
    def get_topic(cls, category):
        """Get learning content for a category."""
        cls.initialize()
        return cls._content.get(category)

    @classmethod
    def get_all_categories(cls):
        """Get all available category keys."""
        cls.initialize()
        return list(cls._content.keys())

    @classmethod
    def get_categories_for_domain(cls, domain_number):
        """Get category keys belonging to a specific domain."""
        cls.initialize()
        from config.exam_objectives import get_objectives
        EXAM_OBJECTIVES = get_objectives()

        domain = EXAM_OBJECTIVES.get(domain_number, {})
        return [c for c in domain.get("categories", []) if c in cls._content]

    @classmethod
    def get_domain_content(cls, domain_number):
        """Get all content dicts for a domain, keyed by category."""
        cls.initialize()
        categories = cls.get_categories_for_domain(domain_number)
        return {cat: cls._content[cat] for cat in categories}
