"""
Task registry system for RHCSA Simulator v4.0.0
Auto-discovers task modules using pkgutil.iter_modules().
"""

import random
import logging
import pkgutil
import importlib
from collections import defaultdict
from typing import List, Optional
from config import settings


logger = logging.getLogger(__name__)


class TaskRegistry:
    """Central registry for all task classes using auto-discovery."""

    _instance = None
    _tasks = defaultdict(list)
    _initialized = False

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    @classmethod
    def register(cls, category):
        """Decorator to register task classes."""
        def wrapper(task_class):
            cls._tasks[category].append(task_class)
            logger.debug(f"Registered task: {task_class.__name__} in category {category}")
            return task_class
        return wrapper

    @classmethod
    def get_all_categories(cls):
        return list(cls._tasks.keys())

    @classmethod
    def get_tasks_by_category(cls, category):
        return cls._tasks.get(category, [])

    @classmethod
    def get_tasks_by_domain(cls, domain_number):
        """Get all task classes for a given exam domain (1-9)."""
        domain_categories = [
            cat for cat, dom in settings.CATEGORY_TO_DOMAIN.items()
            if dom == domain_number
        ]
        tasks = []
        for cat in domain_categories:
            tasks.extend(cls._tasks.get(cat, []))
        return tasks

    @classmethod
    def get_persistence_tasks(cls):
        """Get all task classes that require persistence validation."""
        results = []
        for cat_tasks in cls._tasks.values():
            for task_class in cat_tasks:
                try:
                    instance = task_class()
                    if instance.requires_persistence:
                        results.append(task_class)
                except Exception:
                    pass
        return results

    @classmethod
    def get_tasks_by_tag(cls, tag):
        """Get all task classes with a specific tag."""
        results = []
        for cat_tasks in cls._tasks.values():
            for task_class in cat_tasks:
                try:
                    instance = task_class()
                    if tag in instance.tags:
                        results.append(task_class)
                except Exception:
                    pass
        return results

    @classmethod
    def get_task_count(cls, category=None):
        if category:
            return len(cls._tasks.get(category, []))
        return sum(len(tasks) for tasks in cls._tasks.values())

    @classmethod
    def in_scope(cls, task_class, version=None):
        """True if this task belongs to the exam version being simulated.

        Two gates: the category (settings.VERSION_EXCLUDED_CATEGORIES) and
        the task's own `exam_versions`. A task out of scope must never be
        drawn — grading someone against a syllabus their exam does not use is
        worse than having fewer tasks.
        """
        version = version if version is not None else settings.get_exam_version()
        allowed = getattr(task_class, 'exam_versions', None)
        if allowed is not None and version not in allowed:
            return False
        category = getattr(task_class, 'category', None)
        if category is None:
            # Category is set on the instance, not the class, for most tasks.
            try:
                category = task_class().category
            except Exception:
                return True
        return settings.category_in_scope(category, version)

    @classmethod
    def categories_in_scope(cls, version=None):
        """Registered categories that this exam version actually tests."""
        return [c for c in cls._tasks
                if settings.category_in_scope(c, version)]

    @classmethod
    def get_random_task(cls, category=None, difficulty=None, skip_reboot=False):
        if category:
            if not settings.category_in_scope(category):
                return None
            task_classes = cls._tasks.get(category, [])
        else:
            task_classes = []
            for cat in cls.categories_in_scope():
                task_classes.extend(cls._tasks.get(cat, []))

        if not task_classes:
            return None

        # Drop tasks the active exam version does not cover (e.g. MBR
        # partitioning, which v10 removed).
        task_classes = [tc for tc in task_classes if cls.in_scope(tc)]
        if not task_classes:
            return None

        # Remote tasks are only offered when a lab machine is linked.
        if any(getattr(tc, 'requires_lab_machine', False) for tc in task_classes):
            try:
                from core import lab_machine
                linked = bool(lab_machine.get_host())
            except Exception:
                linked = False
            if not linked:
                task_classes = [tc for tc in task_classes
                                if not getattr(tc, 'requires_lab_machine', False)]
                if not task_classes:
                    return None

        # NFS tasks are only offered once a real NFS server is configured —
        # otherwise generate() falls back to an unreachable placeholder host
        # and the task can never be completed.
        if any(getattr(tc, 'requires_nfs_server', False) for tc in task_classes):
            try:
                from core import nfs_server
                has_server = bool(nfs_server.load_config())
            except Exception:
                has_server = False
            if not has_server:
                task_classes = [tc for tc in task_classes
                                if not getattr(tc, 'requires_nfs_server', False)]
                if not task_classes:
                    return None

        # Tasks flagged as bad ("marked for potential removal") are never
        # offered, in any mode. Manage flags in Setup → Task Statistics.
        try:
            from core import task_flags
            bad_ids = task_flags.flagged_ids()
        except Exception:
            bad_ids = set()
        if bad_ids:
            kept = []
            for tc in task_classes:
                try:
                    if tc().id not in bad_ids:
                        kept.append(tc)
                except Exception:
                    kept.append(tc)
            task_classes = kept
            if not task_classes:
                return None

        # Filter by difficulty
        if difficulty:
            filtered = []
            for tc in task_classes:
                try:
                    inst = tc()
                    if inst.difficulty == difficulty:
                        filtered.append(tc)
                except Exception:
                    pass
            if filtered:
                task_classes = filtered

        # Filter out tasks that require reboots
        if skip_reboot:
            no_reboot = []
            for tc in task_classes:
                try:
                    inst = tc()
                    if not inst.requires_reboot:
                        no_reboot.append(tc)
                except Exception:
                    pass
            if no_reboot:
                task_classes = no_reboot

        if not task_classes:
            return None

        task_class = random.choice(task_classes)
        try:
            task = task_class()
            task.generate()
            return task
        except Exception as e:
            logger.error(f"Error creating task from {task_class.__name__}: {e}")
            return None

    @classmethod
    def get_random_tasks(cls, count, categories=None, difficulty=None, exclude_ids=None, skip_reboot=False):
        tasks = []
        exclude_ids = exclude_ids or []
        attempts = 0
        max_attempts = count * 10

        if categories:
            available_categories = [c for c in categories if c in cls._tasks
                                    and settings.category_in_scope(c)]
        else:
            available_categories = cls.categories_in_scope()

        if not available_categories:
            return []

        while len(tasks) < count and attempts < max_attempts:
            attempts += 1
            category = available_categories[len(tasks) % len(available_categories)]
            task = cls.get_random_task(category=category, difficulty=difficulty, skip_reboot=skip_reboot)
            if task and task.id not in exclude_ids:
                tasks.append(task)
                exclude_ids.append(task.id)

        return tasks

    @classmethod
    def get_exam_tasks(cls, count=None):
        if count is None:
            count = settings.DEFAULT_EXAM_TASKS
        return cls.get_random_tasks(count, difficulty="exam")

    @classmethod
    def generate_exam(cls, count=12, disk_budget=None):
        """
        Generate a balanced exam across all 8 domains.
        60%+ persistence tasks, weighted by domain importance.

        disk_budget caps how many whole-disk tasks (by disk_slots) may be
        selected, so each can later be given a distinct practice device. When
        None it is inferred from how many practice devices can exist — attached
        loops plus free-space capacity for more plus spare real disks — with a
        sane floor, so callers/tests need not pass it.
        """
        tasks = []
        exclude_ids = []

        if disk_budget is None:
            # Loop devices are created on demand at provisioning time, so the
            # budget is what CAN exist (free space + spare real disks), not
            # what is attached right now.
            try:
                from utils.helpers import loop_device_capacity, get_spare_real_disks
                disk_budget = loop_device_capacity() + len(get_spare_real_disks())
            except Exception:
                disk_budget = 0
            disk_budget = max(disk_budget, 3)  # floor: exam start ensures >=3 loops

        # Distribute tasks across domains weighted by domain weight
        from config.exam_objectives import get_objectives
        EXAM_OBJECTIVES = get_objectives()
        total_weight = sum(d["weight"] for d in EXAM_OBJECTIVES.values())

        domain_counts = {}
        remaining = count
        for domain_num in sorted(EXAM_OBJECTIVES.keys()):
            weight = EXAM_OBJECTIVES[domain_num]["weight"]
            domain_counts[domain_num] = max(1, round(count * weight / total_weight))
            remaining -= domain_counts[domain_num]

        # Distribute any remainder
        while remaining > 0:
            for d in sorted(domain_counts, key=lambda x: domain_counts[x]):
                if remaining <= 0:
                    break
                domain_counts[d] += 1
                remaining -= 1

        # Trim if over count
        while sum(domain_counts.values()) > count:
            trimmed = False
            for d in sorted(domain_counts, key=lambda x: -domain_counts[x]):
                if sum(domain_counts.values()) <= count:
                    break
                if domain_counts[d] > 0:
                    domain_counts[d] -= 1
                    trimmed = True
            if not trimmed:
                break

        def _exam_eligible(task):
            """Return True if the task may appear in an exam."""
            if task is None:
                return False
            if getattr(task, 'exam_eligible', True) is False:
                return False
            if getattr(task, 'requires_reboot', False):
                return False
            return True

        # Generate tasks per domain — enforce one task per category to avoid
        # duplicates, and cap whole-disk tasks to disk_budget so each can be
        # assigned a distinct device (no two disk tasks share one disk).
        disk_used = 0
        for domain_num, needed in domain_counts.items():
            domain_cats = [
                cat for cat, dom in settings.CATEGORY_TO_DOMAIN.items()
                if dom == domain_num
            ]
            available_cats = [c for c in domain_cats if c in cls._tasks]
            if not available_cats:
                continue

            used_cats = set()
            remaining_for_domain = needed
            shuffled_cats = available_cats.copy()
            random.shuffle(shuffled_cats)

            for cat in shuffled_cats:
                if remaining_for_domain <= 0:
                    break
                if cat in used_cats:
                    continue
                # Prefer exam difficulty, fall back to any difficulty
                task = cls.get_random_task(category=cat, difficulty="exam")
                if not task:
                    task = cls.get_random_task(category=cat)
                if not _exam_eligible(task):
                    task = None
                if task:
                    slots = getattr(task, 'disk_slots', 0)
                    if slots and disk_used + slots > disk_budget:
                        task = None  # no device left for this disk task
                if task and task.id not in exclude_ids:
                    disk_used += getattr(task, 'disk_slots', 0)
                    tasks.append(task)
                    exclude_ids.append(task.id)
                    used_cats.add(cat)
                    remaining_for_domain -= 1

        # If we couldn't fill all slots, add random tasks (allowing category repeats as last resort)
        guard = 0
        while len(tasks) < count and guard < count * 20:
            guard += 1
            task = cls.get_random_task(difficulty="exam")
            if not _exam_eligible(task):
                task = None
            if task:
                slots = getattr(task, 'disk_slots', 0)
                if slots and disk_used + slots > disk_budget:
                    task = None
            if task and task.id not in exclude_ids:
                disk_used += getattr(task, 'disk_slots', 0)
                tasks.append(task)
                exclude_ids.append(task.id)

        random.shuffle(tasks)
        return tasks

    @classmethod
    def get_practice_tasks(cls, category, difficulty="exam", count=None, skip_reboot=False):
        if count is None:
            count = settings.DEFAULT_PRACTICE_TASKS
        tasks = cls.get_random_tasks(count, categories=[category], difficulty=difficulty, skip_reboot=skip_reboot)
        # Sort by task_order to ensure logical dependency ordering (None = no constraint, sort last)
        tasks.sort(key=lambda t: (t.task_order is None, t.task_order or 0))
        return tasks

    @classmethod
    def initialize(cls):
        """Initialize task registry by auto-discovering all task modules."""
        if cls._initialized:
            return

        logger.info("Initializing task registry (auto-discovery)...")

        import tasks as tasks_package
        package_path = tasks_package.__path__

        for importer, module_name, is_pkg in pkgutil.iter_modules(package_path):
            if module_name in ('base', 'registry', '__init__'):
                continue
            full_module_name = f"tasks.{module_name}"
            try:
                importlib.import_module(full_module_name)
                logger.debug(f"Imported {full_module_name}")
            except ImportError as e:
                logger.warning(f"Could not import {full_module_name}: {e}")
            except Exception as e:
                logger.error(f"Error importing {full_module_name}: {e}")

        cls._initialized = True
        logger.info(
            f"Task registry initialized with {cls.get_task_count()} tasks "
            f"across {len(cls.get_all_categories())} categories"
        )

    @classmethod
    def print_statistics(cls):
        """Print task registry statistics."""
        print("\nTask Registry Statistics:")
        print("=" * 60)
        print(f"Total categories: {len(cls.get_all_categories())}")
        print(f"Total tasks: {cls.get_task_count()}")

        # By domain
        print("\nTasks by Exam Domain:")
        for domain_num, domain_name in sorted(settings.EXAM_DOMAINS.items()):
            domain_tasks = cls.get_tasks_by_domain(domain_num)
            print(f"  Domain {domain_num}: {domain_name} - {len(domain_tasks)} tasks")

        print("\nTasks by Category:")
        for category in sorted(cls.get_all_categories()):
            count = cls.get_task_count(category)
            domain = settings.CATEGORY_TO_DOMAIN.get(category, "?")
            print(f"  {category}: {count} tasks (Domain {domain})")


_registry = TaskRegistry()


def get_registry():
    return _registry
