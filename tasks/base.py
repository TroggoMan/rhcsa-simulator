"""
Base task class for all RHCSA EX200 v10 exam tasks.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import List, Optional
import logging

from config import settings


logger = logging.getLogger(__name__)


class BaseTask(ABC):
    """
    Abstract base class for all RHCSA exam tasks.

    All task categories must inherit from this class and implement
    the generate() and validate() methods.
    """

    # Number of whole practice disks this task consumes (0 = none). The exam
    # generator caps the number of disk tasks to the size of the device pool and
    # hands each one a *distinct* device so they never collide on the same disk.
    disk_slots = 0

    # True if this task establishes a "negative precondition" at exam start so
    # the candidate must actually do the work (e.g. stop a default-on service,
    # move an existing artifact aside). The exam loop calls setup_environment()
    # during preparation and teardown_environment() during cleanup. Without this,
    # positive-config tasks can pass on pre-existing/default state.
    has_setup = False

    # Packages this task's fault injection / scenario needs to be fully real
    # (e.g. httpd for an Apache troubleshooting fault). Session prep collects
    # these and OFFERS to install what's missing (never installs silently). If
    # the user declines, the task must degrade gracefully — reduced scenario,
    # fabricated log evidence, or descriptive-only.
    required_packages = []

    # Exam versions this task is in scope for. None = both. Set it when a
    # category is in scope for both versions but one task inside it is not —
    # MBR partitioning is v9-only, because v10's objective reads "List,
    # create, and delete partitions on GPT disks". Whole categories are
    # filtered by settings.VERSION_EXCLUDED_CATEGORIES instead.
    exam_versions = None

    # True for tasks performed ON the linked second lab machine (over SSH).
    # They are only offered when a lab machine is linked (Setup → Link second
    # lab machine); the registry filters them out otherwise.
    requires_lab_machine = False

    # True for tasks that mount/automount from a *real* NFS server
    # (core/nfs_server.py). Without one configured (Setup → Configure remote
    # NFS server) there is nothing reachable to mount, so generate() falls
    # back to a placeholder hostname like server1.example.com that can never
    # succeed — the task would be unpassable. The registry filters these out
    # until a server is configured, exactly like requires_lab_machine.
    requires_nfs_server = False

    def __init__(self, id, category, difficulty, points):
        self.id = id
        self.category = category
        self.difficulty = difficulty
        self.points = points
        self.description = ""
        self.hints = []
        self.params = {}

        # v4.0.0 additions
        self.exam_domain = settings.CATEGORY_TO_DOMAIN.get(category, 0)
        self.requires_persistence = False
        self.persistence_checks = []
        self.exam_tips = []
        self.prerequisites = []
        self.tags = []
        self.task_order = None  # None = no ordering constraint; int = logical sequence within category
        self.requires_reboot = False  # True if completing this task requires rebooting the system

    @abstractmethod
    def generate(self, **params):
        """Generate task with randomized parameters. Returns self."""
        pass

    @abstractmethod
    def validate(self):
        """Validate task completion. Returns ValidationResult."""
        pass

    def provision_devices(self):
        """Re-bind this task to freshly-allocated practice device(s).

        Called once during exam generation while the device allocator is active.
        The default re-runs generate(), so any task whose generate() pulls a
        device via helpers.get_practice_device()/get_swap_practice_device() will
        pick a *distinct* device from the allocator. Multi-disk tasks override
        this to allocate the right number of devices.
        """
        if self.disk_slots:
            self.generate()

    def setup_environment(self):
        """Establish the negative precondition for this task at exam start.

        Override in tasks that would otherwise pass on pre-existing/default
        state. Return (ok: bool, message: str). Default: no-op.
        """
        return True, "no setup needed"

    def teardown_environment(self):
        """Restore whatever setup_environment() changed.

        The default replays the restore record saved via tasks/env_setup.py
        helpers (resilient to interruption — System Reset and startup recovery
        use the same record).
        """
        from tasks import env_setup
        return env_setup.restore_and_clear(self.id)

    def validate_persistence(self):
        """
        Validate that task results survive a reboot.
        Called by the reboot engine for tasks with requires_persistence=True.
        Default: falls through to validate().
        """
        return self.validate()

    def get_description(self):
        return self.description

    def get_hints(self):
        return self.hints

    def get_category_display_name(self):
        from utils.formatters import format_category_name
        return format_category_name(self.category)

    def get_difficulty_display(self):
        from utils.formatters import format_difficulty
        return format_difficulty(self.difficulty)

    def get_domain_display(self):
        return settings.EXAM_DOMAINS.get(self.exam_domain, "Unknown")

    def to_dict(self):
        return {
            'id': self.id,
            'category': self.category,
            'difficulty': self.difficulty,
            'points': self.points,
            'description': self.description,
            'hints': self.hints,
            'exam_domain': self.exam_domain,
            'requires_persistence': self.requires_persistence,
            'tags': self.tags,
            'exam_tips': self.exam_tips,
        }

    def __repr__(self):
        return f"<Task {self.id}: {self.category} ({self.difficulty}, {self.points}pts, D{self.exam_domain})>"


class SimpleTask(BaseTask):
    """Non-abstract implementation for quick task creation."""

    def __init__(self, id, category, difficulty, points, description="", validation_func=None):
        super().__init__(id, category, difficulty, points)
        self.description = description
        self._validation_func = validation_func

    def generate(self, **params):
        return self

    def validate(self):
        if self._validation_func:
            return self._validation_func()

        from core.validator import ValidationResult
        return ValidationResult(
            task_id=self.id,
            passed=False,
            score=0,
            max_score=self.points,
            error_message="No validation function provided"
        )
