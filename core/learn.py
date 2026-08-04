"""
Learn Mode v4.0.0 - Domain-based learning with SM-2 spaced repetition.
UI dispatcher that loads content from core.content modules.
"""

import logging
from utils import formatters as fmt
from core.content import ContentRegistry
from config.exam_objectives import get_objectives

logger = logging.getLogger(__name__)


class LearnMode:
    """Domain-based learn mode with SM-2 indicators and practice integration."""

    def __init__(self):
        self._db = None

    @property
    def db(self):
        if self._db is None:
            try:
                from core.results_db import get_results_db
                self._db = get_results_db()
            except Exception:
                self._db = None
        return self._db

    def _get_weak_categories(self):
        """Get set of weak category names."""
        if not self.db:
            return set()
        try:
            return {r["category"] for r in self.db.get_weak_categories(0.7)}
        except Exception:
            return set()

    def _get_due_categories(self):
        """Get set of categories due for spaced repetition."""
        if not self.db:
            return set()
        try:
            return {r["category"] for r in self.db.get_due_categories()}
        except Exception:
            return set()

    def _format_sm2_indicator(self, categories, weak_cats, due_cats):
        """Build SM-2 indicator string for a list of categories."""
        indicators = []
        for cat in categories:
            if cat in weak_cats:
                indicators.append(fmt.error("[WEAK AREA]"))
            elif cat in due_cats:
                indicators.append(fmt.warning("[DUE FOR REVIEW]"))
        # Deduplicate - show most severe per domain
        if any(cat in weak_cats for cat in categories):
            return f" {fmt.error('[WEAK AREA]')}"
        if any(cat in due_cats for cat in categories):
            return f" {fmt.warning('[DUE FOR REVIEW]')}"
        return ""

    def start(self):
        """Start learn mode - domain selection menu."""
        ContentRegistry.initialize()
        weak_cats = self._get_weak_categories()
        due_cats = self._get_due_categories()

        while True:
            fmt.clear_screen()
            # Learn mode must show the syllabus the candidate will be graded
            # against — v9 has a Containers domain that v10 does not.
            from config import settings
            EXAM_OBJECTIVES = get_objectives()
            fmt.print_header(
                f"LEARN MODE - EX200 v{settings.get_exam_version()} Exam Domains")
            print()

            for domain_num in sorted(EXAM_OBJECTIVES.keys()):
                domain = EXAM_OBJECTIVES[domain_num]
                name = domain["name"]
                weight = domain["weight"]
                categories = ContentRegistry.get_categories_for_domain(domain_num)
                indicator = self._format_sm2_indicator(
                    categories, weak_cats, due_cats
                )
                cat_count = len(categories)
                fmt.print_menu_option(
                    domain_num,
                    f"{name} ({weight}% weight, {cat_count} topics){indicator}",
                )

            print()
            fmt.print_menu_option("Q", "Back to Main Menu")

            max_domain = max(EXAM_OBJECTIVES.keys())
            choice = input(f"\nSelect domain (1-{max_domain} or Q): ").strip()

            if choice.lower() == "q":
                return

            try:
                domain_num = int(choice)
                if domain_num in EXAM_OBJECTIVES:
                    self._show_domain_topics(domain_num, weak_cats, due_cats)
                else:
                    print(fmt.error(f"Invalid selection. Choose 1-{max_domain}."))
                    input("Press Enter to continue...")
            except ValueError:
                print(fmt.error("Please enter a number or Q"))
                input("Press Enter to continue...")

    def _show_domain_topics(self, domain_num, weak_cats, due_cats):
        """Show topics within a domain."""
        domain = get_objectives()[domain_num]
        categories = ContentRegistry.get_categories_for_domain(domain_num)

        if not categories:
            print(fmt.warning("No content available for this domain yet."))
            input("Press Enter to continue...")
            return

        while True:
            fmt.clear_screen()
            fmt.print_header(
                f"Domain {domain_num}: {domain['name']} ({domain['weight']}%)"
            )
            print()

            # Show objectives
            print(fmt.bold("Exam Objectives:"))
            for obj in domain["objectives"]:
                print(f"  - {obj}")
            print()

            # Show topic list
            print(fmt.bold("Topics:"))
            for i, cat in enumerate(categories, 1):
                topic = ContentRegistry.get_topic(cat)
                if not topic:
                    continue
                indicator = ""
                if cat in weak_cats:
                    indicator = f" {fmt.error('[WEAK AREA]')}"
                elif cat in due_cats:
                    indicator = f" {fmt.warning('[DUE FOR REVIEW]')}"

                stats = self._get_category_stats(cat)
                fmt.print_menu_option(i, f"{topic['name']}{indicator}{stats}")

            print()
            fmt.print_menu_option("B", "Back to domains")

            choice = input("\nSelect topic (number or B): ").strip()

            if choice.lower() == "b":
                return

            try:
                idx = int(choice) - 1
                if 0 <= idx < len(categories):
                    self._display_topic(categories[idx])
                else:
                    print(fmt.error("Invalid selection"))
                    input("Press Enter to continue...")
            except ValueError:
                print(fmt.error("Please enter a number or B"))
                input("Press Enter to continue...")

    def _get_category_stats(self, category):
        """Get a brief stats string for a category."""
        if not self.db:
            return ""
        try:
            stats = self.db.get_category_stats(category)
            if stats and stats["attempts"] > 0:
                rate = stats["success_rate"]
                pct = int(rate * 100)
                attempts = stats["attempts"]
                return f" {fmt.dim(f'({pct}% in {attempts} attempts)')}"
        except Exception:
            pass
        return ""

    def _display_topic(self, category):
        """Display learning content for a topic."""
        topic = ContentRegistry.get_topic(category)
        if not topic:
            print(fmt.error(f"No content found for '{category}'"))
            input("Press Enter to continue...")
            return

        fmt.clear_screen()
        fmt.print_header(f"LEARN: {topic['name']}")

        # Explanation
        print(fmt.bold("CONCEPT OVERVIEW:"))
        print(topic["explanation"].strip())
        print()

        # Commands
        print(fmt.bold("ESSENTIAL COMMANDS:"))
        print("=" * 70)
        for cmd in topic["commands"]:
            print()
            print(fmt.success(f"  {cmd['name']}"))
            print()
            print(fmt.bold("  Syntax:"))
            print(f"    {fmt.info(cmd['syntax'])}")
            print()
            print(fmt.bold("  Example:"))
            for line in cmd["example"].split("\n"):
                print(f"    $ {line}")
            print()
            print(fmt.bold("  Flags:"))
            for flag, description in cmd["flags"].items():
                print(f"    {fmt.warning(flag):20} -> {description}")
            print()

        # Common Mistakes
        print("=" * 70)
        print(fmt.bold("COMMON MISTAKES:"))
        for i, mistake in enumerate(topic["common_mistakes"], 1):
            print(f"  {i}. {fmt.error('X')} {mistake}")
        print()

        # Exam Tricks
        print(fmt.bold("EXAM TIPS:"))
        for i, trick in enumerate(topic["exam_tricks"], 1):
            print(f"  {i}. {fmt.warning('!')} {trick}")
        print()

        # Navigation
        print("=" * 70)
        choice = (
            input("\n[P] Practice this topic  [B] Back to topics  [Q] Main menu: ")
            .strip()
            .lower()
        )

        if choice == "p":
            self._launch_practice(category)
        elif choice == "q":
            return

    def _launch_practice(self, category):
        """Launch practice tasks for a category."""
        try:
            from tasks.registry import TaskRegistry

            TaskRegistry.initialize()
            tasks = TaskRegistry.get_practice_tasks(category, "exam", 3)

            if not tasks:
                # Fall back to any difficulty
                tasks = TaskRegistry.get_practice_tasks(category, None, 3)

            if not tasks:
                print(
                    fmt.warning(
                        "No practice tasks available for this topic yet."
                    )
                )
                input("Press Enter to continue...")
                return

            from core.practice import PracticeSession

            session = PracticeSession()
            session.category = category
            session.difficulty = "exam"
            session.task_count = len(tasks)

            for i, task in enumerate(tasks, 1):
                session._run_practice_task(task, i, len(tasks))
        except ImportError as e:
            logger.warning(f"Could not launch practice: {e}")
            print(fmt.warning("Practice mode not available."))
            input("Press Enter to continue...")
        except Exception as e:
            logger.error(f"Practice error: {e}")
            print(fmt.error(f"Error launching practice: {e}"))
            input("Press Enter to continue...")


def run_learn_mode(category=None):
    """Run learn mode (convenience function).

    Args:
        category: Optional category to jump directly to
    """
    mode = LearnMode()
    if category:
        mode._display_topic(category)
    else:
        mode.start()
