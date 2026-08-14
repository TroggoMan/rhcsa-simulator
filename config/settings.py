"""
Global configuration settings for RHCSA EX200 v10 Simulator v4.0.0
"""

import os
from pathlib import Path

# Installation paths
INSTALL_DIR = Path("/opt/rhcsa-simulator")
CONFIG_DIR = INSTALL_DIR / "config"
DATA_DIR = INSTALL_DIR / "data"
RESULTS_DIR = DATA_DIR / "results"

# Development mode (use local paths if not installed)
if not INSTALL_DIR.exists():
    INSTALL_DIR = Path(__file__).parent.parent
    CONFIG_DIR = INSTALL_DIR / "config"
    DATA_DIR = INSTALL_DIR / "data"
    RESULTS_DIR = DATA_DIR / "results"

# Create data directories if they don't exist
RESULTS_DIR.mkdir(parents=True, exist_ok=True)

# SQLite database path
DB_PATH = DATA_DIR / "rhcsa_simulator.db"

# Exam configuration - v10 aligned
DEFAULT_EXAM_DURATION = 180  # minutes (3 hours - real exam)
DEFAULT_EXAM_TASKS = 20  # real exam is 20-25 tasks
EXAM_TASK_RANGE = (20, 25)
MAX_EXAM_SCORE = 300  # matches real exam
EXAM_PASS_THRESHOLD = 0.70  # 70% to pass

# Reboot simulation
REBOOT_SIMULATION = True

# Task configuration
DIFFICULTY_LEVELS = ["easy", "medium", "exam", "hard"]
TASK_CATEGORIES = [
    "users_groups",
    "permissions",
    "essential_tools",
    "lvm",
    "filesystems",
    "networking",
    "ssh",
    "selinux",
    "services",
    "processes",
    "time_services",
    "troubleshooting",
    "boot",
    "scheduling",
    "scripting",
    "packages",
    "partitioning",
    "network_storage",
    "repos",
    "flatpak",
    "boot_recovery",
    "journalctl",
    "systemd_timers",
    "firewall",
    "swap",
]

# ---------------------------------------------------------------------------
# Exam version (EX200 v9 vs v10)
#
# The two exams differ by more than a rename, and not symmetrically:
#
#   v9 only   Manage containers (podman/skopeo) — a whole objective section
#             MBR partition tables ("MBR and GPT disks")
#             set-GID collaboration directories
#             "Diagnose and address routine SELinux policy violations"
#   v10 only  Flatpak repositories and packages
#             systemd timer units as a scheduling mechanism
#             (v10 also drops MBR: "List, create, and delete partitions on
#             GPT disks")
#
# Everything else is identical or a wording change (superuser -> privileged
# access, Red Hat Network -> Red Hat CDN). Rather than fork the task set, one
# catalogue carries both and the out-of-scope pieces are filtered per version.
# ---------------------------------------------------------------------------

SUPPORTED_EXAM_VERSIONS = (9, 10)
DEFAULT_EXAM_VERSION = 10

_active_exam_version = DEFAULT_EXAM_VERSION


def get_exam_version():
    """The EX200 version currently being simulated (9 or 10)."""
    return _active_exam_version


def set_exam_version(version):
    """Switch the simulated exam version. Raises ValueError on anything else —
    silently falling back would mean grading against the wrong syllabus."""
    version = int(version)
    if version not in SUPPORTED_EXAM_VERSIONS:
        raise ValueError(
            "unsupported exam version %r (expected one of %s)"
            % (version, ', '.join(str(v) for v in SUPPORTED_EXAM_VERSIONS)))
    global _active_exam_version
    _active_exam_version = version
    return _active_exam_version


# Categories that are out of scope for a given exam version. Task classes can
# additionally opt out individually via `exam_versions` (see tasks/base.py) —
# used where a whole category is in scope but one task inside it is not, as
# with MBR partitioning.
VERSION_EXCLUDED_CATEGORIES = {
    9: {
        "flatpak",         # no Flatpak objective exists in EX200 v9
        "systemd_timers",  # v9 scheduling objective is "at and cron" only
    },
    10: {
        "containers",      # v10 dropped the Manage containers section
    },
}


def excluded_categories(version=None):
    """Categories out of scope for this exam version."""
    version = version if version is not None else get_exam_version()
    return VERSION_EXCLUDED_CATEGORIES.get(version, set())


def category_in_scope(category, version=None):
    return category not in excluded_categories(version)


# Exam Domains. 1-8 apply to both versions; 9 exists only in v9, where
# "Manage containers" is its own objective section.
EXAM_DOMAINS = {
    1: "Software Management",
    2: "System Setup & Boot",
    3: "Users, Groups & Permissions",
    4: "Storage & Filesystems",
    5: "Network & DNS",
    6: "Systemd, Services & Processes",
    7: "Security - SELinux & Firewall",
    8: "Automation & Scripting",
    9: "Containers",
}


def exam_domains(version=None):
    """Domain number -> name for this exam version."""
    version = version if version is not None else get_exam_version()
    if version == 9:
        return dict(EXAM_DOMAINS)
    return {n: name for n, name in EXAM_DOMAINS.items() if n != 9}


# Map categories to domains (the union across versions; filtering is done by
# VERSION_EXCLUDED_CATEGORIES, so a category keeps its domain either way).
CATEGORY_TO_DOMAIN = {
    "packages": 1, "repos": 1, "flatpak": 1,
    "boot": 2, "boot_recovery": 2, "journalctl": 2,
    "users_groups": 3, "permissions": 3, "essential_tools": 3,
    "partitioning": 4, "lvm": 4, "filesystems": 4, "swap": 4, "network_storage": 4,
    "networking": 5, "ssh": 5,
    "services": 6, "systemd_timers": 6, "processes": 6, "time_services": 6, "troubleshooting": 6,
    "selinux": 7, "firewall": 7,
    "scheduling": 8, "scripting": 8,
    "containers": 9,
}

# Practice mode configuration
DEFAULT_PRACTICE_TASKS = 5
SHOW_HINTS_DEFAULT = True
IMMEDIATE_FEEDBACK_DEFAULT = True

# Validation configuration
COMMAND_TIMEOUT = 5  # seconds
MAX_RETRIES = 3

# Point values by difficulty
POINTS_BY_DIFFICULTY = {
    "easy": (3, 8),
    "medium": (8, 12),
    "exam": (10, 20),
    "hard": (15, 20),
}

# Safe commands whitelist for validation (read-only operations)
SAFE_VALIDATION_COMMANDS = {
    # User management (read-only)
    'id', 'getent', 'groups', 'whoami',

    # Filesystem info
    'df', 'mount', 'lsblk', 'blkid', 'findmnt', 'xfs_info', 'tune2fs',
    'dumpe2fs', 'file', 'swapon', 'free',

    # LVM info
    'pvs', 'vgs', 'lvs', 'pvdisplay', 'vgdisplay', 'lvdisplay',

    # File/directory operations (read-only)
    'ls', 'stat', 'getfacl', 'cat', 'head', 'tail', 'find',

    # Network info
    'ip', 'nmcli', 'hostnamectl', 'hostname', 'ss', 'ping',

    # Firewall info
    'firewall-cmd',

    # SELinux info
    'getenforce', 'getsebool', 'semanage', 'sestatus', 'matchpathcon',
    'ausearch', 'audit2why', 'sealert',

    # Service/systemd info
    'systemctl', 'journalctl',

    # SSH config test (read-only, -t only — see _validate_specific_commands)
    'sshd',

    # sudo privilege listing / sudoers syntax check (read-only — see
    # _validate_specific_commands: sudo requires -l, visudo requires -c)
    'sudo', 'visudo',

    # Process info
    'ps', 'top', 'pgrep', 'pidof',

    # Scheduling
    'crontab', 'atq', 'at',

    # Package management (read-only)
    'rpm', 'dnf', 'yum',

    # Flatpak (read-only)
    'flatpak',

    # Containers — read-only subcommands only, enforced in
    # validators/safe_executor.py (_validate_specific_commands). v9 only.
    'podman', 'skopeo',

    # Time services (read-only)
    'timedatectl', 'chronyc',

    # Network storage (read-only)
    'showmount', 'exportfs',

    # Partitioning (read-only - query only)
    'parted', 'fdisk', 'gdisk', 'partprobe',

    # Shell/scripting (read-only)
    'bash', 'test', 'which', 'type',

    # Boot analysis
    'systemd-analyze', 'grubby',

    # Miscellaneous
    'grep', 'awk', 'sed', 'cut', 'sort', 'uniq', 'wc', 'date',
    'chage', 'passwd',
}

# Dangerous patterns to block (security)
DANGEROUS_PATTERNS = [
    r';\s*rm\s+-rf',
    r'\|\s*sh',
    r'\|\s*bash',
    r'`.*`',
    r'\$\(',
    r'>\s*/dev/',
    r'>\s*/etc/',
    r'dd\s+.*of=/dev/',
    r'mkfs',
]

# Logging configuration
LOG_DIR = DATA_DIR / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)
LOG_FILE = LOG_DIR / "rhcsa_simulator.log"
LOG_LEVEL = "INFO"
LOG_FORMAT = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
LOG_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"

# Display configuration
USE_COLOR = True
DISPLAY_WIDTH = 80
SHOW_PROGRESS_BAR = True

# Timer configuration
TIMER_WARNING_MINUTES = 30
TIMER_CHECK_INTERVAL = 60

# Result file configuration
RESULT_FILE_PREFIX = "exam_result_"
RESULT_FILE_SUFFIX = ".json"
MAX_STORED_RESULTS = 100

# Version
VERSION = "4.0.0"
APP_NAME = "RHCSA EX200 v10 Exam Simulator"
