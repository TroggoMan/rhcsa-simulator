"""
EX200 Exam Objectives — formal domain definitions with weights and mapped
categories, per exam version.

Domains 1-8 are this simulator's own grouping of the official study points;
domain 9 (Containers) exists only in v9, where "Manage containers" is its own
section on Red Hat's page. Weights are the simulator's estimate — Red Hat does
not publish per-section weightings.

Call get_objectives() rather than touching the version dicts directly, so a
session always sees the syllabus it is being graded against.
"""

from config import settings

OBJECTIVES_V10 = {
    1: {
        "name": "Software Management",
        "weight": 12,
        "objectives": [
            "Install and update software packages using dnf",
            "Configure package repositories (BaseOS, AppStream, third-party)",
            "Manage RPM packages (query, verify, install)",
            "Install and manage Flatpak applications and repositories",
            "Manage package groups and environments",
        ],
        "categories": ["packages", "repos", "flatpak"],
    },
    2: {
        "name": "System Setup & Boot",
        "weight": 11,
        "objectives": [
            "Set default boot target (multi-user, graphical)",
            "Configure GRUB2 boot loader parameters",
            "Reset root password using rd.break",
            "Boot into emergency and rescue targets",
            "Analyze and troubleshoot boot issues",
            "Configure persistent journal logging",
            "Use journalctl to filter and analyze logs",
        ],
        "categories": ["boot", "boot_recovery", "journalctl"],
    },
    3: {
        "name": "Users, Groups & Permissions",
        "weight": 12,
        "objectives": [
            "Create, delete, and modify local user accounts",
            "Create and manage groups",
            "Configure password aging policies",
            "Configure sudo access for users and groups",
            "Set file and directory permissions (chmod)",
            "Set file ownership (chown, chgrp)",
            "Configure and manage ACLs (setfacl, getfacl)",
            "Set special permissions (SGID, SUID, sticky bit)",
            "Configure umask for default permissions",
        ],
        "categories": ["users_groups", "permissions"],
    },
    4: {
        "name": "Storage & Filesystems",
        "weight": 19,
        "objectives": [
            "Create MBR and GPT partitions",
            "Create and manage LVM (PV, VG, LV)",
            "Extend and resize logical volumes",
            "Create ext4, XFS, and VFAT filesystems",
            "Mount filesystems persistently via /etc/fstab",
            "Mount filesystems with specific options",
            "Configure swap space (partition and file)",
            "Mount NFS shares persistently",
            "Configure autofs for on-demand mounting",
        ],
        "categories": ["partitioning", "lvm", "filesystems", "swap", "network_storage"],
    },
    5: {
        "name": "Network & DNS",
        "weight": 10,
        "objectives": [
            "Configure static and dynamic network connections using nmcli",
            "Set system hostname",
            "Configure DNS resolution (/etc/resolv.conf, nmcli)",
            "Configure /etc/hosts for name resolution",
            "Add static routes",
            "Troubleshoot network connectivity",
            "Configure IPv6 addresses",
        ],
        "categories": ["networking"],
    },
    6: {
        "name": "Systemd, Services & Processes",
        "weight": 12,
        "objectives": [
            "Start, stop, enable, and disable services",
            "Mask and unmask services",
            "View service status and logs",
            "Create and manage systemd timers",
            "Configure timer-based recurring tasks",
            "Manage running processes (kill, nice, renice)",
        ],
        "categories": ["services", "systemd_timers"],
    },
    7: {
        "name": "Security - SELinux & Firewall",
        "weight": 14,
        "objectives": [
            "Set SELinux enforcing and permissive modes",
            "Set SELinux file contexts and restore defaults",
            "Configure SELinux booleans",
            "Configure SELinux port contexts",
            "Diagnose and troubleshoot SELinux denials (audit2why, sealert)",
            "Configure firewalld zones, services, and ports",
            "Add rich rules and port forwarding",
            "Make firewall rules permanent",
        ],
        "categories": ["selinux", "firewall"],
    },
    8: {
        "name": "Automation & Scripting",
        "weight": 10,
        "objectives": [
            "Schedule recurring tasks with cron",
            "Schedule one-time tasks with at",
            "Write correct cron expressions",
            "Restrict cron access for users",
            "Write basic bash scripts with conditionals and loops",
            "Write scripts with command-line arguments",
            "Use exit codes in scripts",
        ],
        "categories": ["scheduling", "scripting"],
    },
}


# ---------------------------------------------------------------------------
# v9 differences, taken from Red Hat's EX200 (RHEL 9) study points:
#
#   - No "Manage software" section and no Flatpak at all. Software install
#     lives under "Deploy, configure, and maintain systems".
#   - "List, create, delete partitions on MBR and GPT disks" (v10: GPT only).
#   - "Create and configure set-GID directories for collaboration"
#     (dropped in v10).
#   - "Schedule tasks using at and cron" — no systemd timer units.
#   - "Diagnose and address routine SELinux policy violations"
#     (dropped in v10).
#   - "Manage containers" is a section of its own — domain 9 below.
#
# Weight is redistributed to give containers ~10%, taken proportionally from
# the domains that lose objectives in v9 (software, systemd/services).
# ---------------------------------------------------------------------------

OBJECTIVES_V9 = {
    1: {
        "name": "Software Management",
        "weight": 10,
        "objectives": [
            "Install and update software packages using dnf/yum",
            "Install and update software packages from Red Hat Network, a "
            "remote repository, or from the local file system",
            "Configure access to RPM repositories (BaseOS, AppStream, "
            "third-party)",
            "Manage RPM packages (query, verify, install)",
            "Manage package groups and environments",
        ],
        "categories": ["packages", "repos"],
    },
    2: {
        "name": "System Setup & Boot",
        "weight": 11,
        "objectives": [
            "Set default boot target (multi-user, graphical)",
            "Configure GRUB2 boot loader parameters",
            "Interrupt the boot process to gain access to a system "
            "(rd.break root password reset)",
            "Boot into emergency and rescue targets",
            "Modify the system bootloader",
            "Locate and interpret system log files and journals",
            "Preserve system journals",
        ],
        "categories": ["boot", "boot_recovery", "journalctl"],
    },
    3: {
        "name": "Users, Groups & Permissions",
        "weight": 12,
        "objectives": [
            "Create, delete, and modify local user accounts",
            "Change passwords and adjust password aging for local accounts",
            "Create, delete, and modify local groups and group memberships",
            "Configure superuser access",
            "List, set, and change standard ugo/rwx permissions",
            "Manage default file permissions (umask)",
            "Create and configure set-GID directories for collaboration",
            "Diagnose and correct file permission problems",
        ],
        "categories": ["users_groups", "permissions", "essential_tools"],
    },
    4: {
        "name": "Storage & Filesystems",
        "weight": 18,
        "objectives": [
            "List, create, delete partitions on MBR and GPT disks",
            "Create and remove physical volumes",
            "Assign physical volumes to volume groups",
            "Create and delete logical volumes",
            "Extend existing logical volumes",
            "Create, mount, unmount, and use vfat, ext4, and xfs file systems",
            "Configure systems to mount file systems at boot by UUID or label",
            "Add new partitions, logical volumes and swap non-destructively",
            "Mount and unmount network file systems using NFS",
            "Configure autofs",
        ],
        "categories": ["partitioning", "lvm", "filesystems", "swap",
                       "network_storage"],
    },
    5: {
        "name": "Network & DNS",
        "weight": 10,
        "objectives": [
            "Configure IPv4 and IPv6 addresses",
            "Configure hostname resolution",
            "Configure network services to start automatically at boot",
            "Access remote systems using SSH",
            "Configure key-based authentication for SSH",
            "Securely transfer files between systems",
        ],
        "categories": ["networking", "ssh"],
    },
    6: {
        "name": "Systemd, Services & Processes",
        "weight": 10,
        "objectives": [
            "Start and stop services and configure them to start at boot",
            "Start, stop, and check the status of network services",
            "Configure systems to boot into a specific target automatically",
            "Identify CPU/memory intensive processes and kill processes",
            "Adjust process scheduling",
            "Manage tuning profiles",
            "Configure time service clients",
        ],
        "categories": ["services", "processes", "time_services",
                       "troubleshooting"],
    },
    7: {
        "name": "Security - SELinux & Firewall",
        "weight": 13,
        "objectives": [
            "Set enforcing and permissive modes for SELinux",
            "List and identify SELinux file and process context",
            "Restore default file contexts",
            "Manage SELinux port labels",
            "Use boolean settings to modify system SELinux settings",
            "Diagnose and address routine SELinux policy violations",
            "Configure firewall settings using firewall-cmd/firewalld",
            "Restrict network access using firewall-cmd/firewall",
        ],
        "categories": ["selinux", "firewall"],
    },
    8: {
        "name": "Automation & Scripting",
        "weight": 6,
        "objectives": [
            "Schedule tasks using at and cron",
            "Write correct cron expressions",
            "Restrict cron access for users",
            "Conditionally execute code (if, test, [], etc.)",
            "Use looping constructs (for, etc.) to process input",
            "Process script inputs ($1, $2, etc.)",
            "Process output of shell commands within a script",
        ],
        "categories": ["scheduling", "scripting"],
    },
    9: {
        "name": "Containers",
        "weight": 10,
        "objectives": [
            "Find and retrieve container images from a remote registry",
            "Inspect container images",
            "Perform container management using commands such as podman and "
            "skopeo",
            "Perform basic container management such as running, starting, "
            "stopping, and listing running containers",
            "Run a service inside a container",
            "Configure a container to start automatically as a systemd "
            "service",
            "Attach persistent storage to a container",
        ],
        "categories": ["containers"],
    },
}

_BY_VERSION = {9: OBJECTIVES_V9, 10: OBJECTIVES_V10}


def get_objectives(version=None):
    """Objective table for an exam version (defaults to the active one)."""
    if version is None:
        version = settings.get_exam_version()
    return _BY_VERSION.get(version, OBJECTIVES_V10)


def get_domain_weight(domain_number, version=None):
    """Get the weight percentage for a domain."""
    return get_objectives(version).get(domain_number, {}).get("weight", 0)


def get_domain_categories(domain_number, version=None):
    """Get all task categories for a domain."""
    return get_objectives(version).get(domain_number, {}).get("categories", [])


def get_domain_name(domain_number, version=None):
    """Get the display name for a domain."""
    return get_objectives(version).get(domain_number, {}).get("name", "Unknown")
