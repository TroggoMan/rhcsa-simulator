"""
Preflight package check.

Several troubleshooting fault-injectors and positive-configuration tasks
assume common exam-relevant packages already exist on the box (httpd,
vsftpd, nfs-utils, samba, chrony...). A minimal RHEL/Rocky/Alma install
often doesn't have them. When a package is missing, a task's
inject_fault()/setup_environment() call still "succeeds" (its own commands
just no-op or fail silently) so the resulting scenario looks like it was
never created — e.g. an httpd 403 troubleshooting task where httpd was
never actually running.

This module runs a read-only `rpm -q` check at startup and warns about
what's missing so the gap is visible up front instead of surfacing later
as a confusing "nothing happened" task.
"""

import subprocess

from utils import formatters as fmt

# package -> which tasks need it
REQUIRED_PACKAGES = {
    'httpd': 'Apache web server tasks (SELinux, firewall, service troubleshooting)',
    'vsftpd': 'FTP service tasks',
    'nfs-utils': 'NFS server/client and network storage tasks',
    'samba': 'Samba/SMB file sharing tasks',
    'chrony': 'time synchronization tasks',
    'firewalld': 'firewall management and troubleshooting tasks',
    'bind-utils': 'DNS lookup tooling used by networking tasks',
    'tuned': 'tuning profile (tuned-adm) tasks',
}

# Packages only some exam versions need. v10 dropped the containers section
# entirely, so warning a v10 candidate about podman would be noise.
VERSION_PACKAGES = {
    9: {
        'podman': 'container tasks (v9 "Manage containers" objectives)',
        'skopeo': 'remote container image inspection (v9)',
    },
}


def required_packages(version=None):
    """REQUIRED_PACKAGES plus anything this exam version adds."""
    from config import settings
    version = version if version is not None else settings.get_exam_version()
    packages = dict(REQUIRED_PACKAGES)
    packages.update(VERSION_PACKAGES.get(version, {}))
    return packages


def _rpm_installed(pkg):
    """True/False if rpm can answer, None if rpm itself isn't available
    (e.g. a non-RPM environment such as a CI container)."""
    try:
        r = subprocess.run(['rpm', '-q', pkg], capture_output=True, text=True, timeout=10)
        return r.returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return None


def check_dependencies(packages=None):
    """Return {pkg: True|False|None} for each of REQUIRED_PACKAGES (or the
    given package list). None means installation status is unknown."""
    packages = packages if packages is not None else required_packages()
    return {pkg: _rpm_installed(pkg) for pkg in packages}


def missing_packages(statuses=None):
    """Packages confirmed NOT installed (excludes unknown/None statuses)."""
    statuses = statuses if statuses is not None else check_dependencies()
    return sorted(pkg for pkg, installed in statuses.items() if installed is False)


def filter_missing(packages):
    """Subset of `packages` confirmed NOT installed (rpm answered). Unknown
    statuses (no rpm binary, timeout) are excluded — never offer to install
    something we can't verify is absent."""
    return sorted(pkg for pkg in set(packages) if _rpm_installed(pkg) is False)


def install_packages(packages):
    """dnf-install the given packages. Returns (ok, output). Only ever called
    after the user has explicitly consented — never call this unprompted."""
    if not packages:
        return True, ""
    try:
        r = subprocess.run(['dnf', 'install', '-y', *sorted(set(packages))],
                           capture_output=True, text=True, timeout=600)
        return r.returncode == 0, (r.stdout or '') + (r.stderr or '')
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError) as e:
        return False, str(e)


def offer_task_packages(tasks):
    """Session-prep package prompt.

    Gathers required_packages from the generated tasks; for any that are
    missing, asks the user (Y/n) whether to install them. NOTHING is installed
    without consent. Returns the list of packages still missing afterwards so
    fault injectors can fall back (reduced scenario / fabricated evidence).
    """
    needed = set()
    for t in tasks or []:
        needed.update(getattr(t, 'required_packages', []) or [])
    if not needed:
        return []
    missing = filter_missing(needed)
    if not missing:
        return []

    from utils.helpers import confirm_action
    print(fmt.warning(
        f"\nSome tasks in this session use package(s) not installed on this "
        f"system: {', '.join(missing)}"))
    print(fmt.dim("  Without them those scenarios run in a reduced mode "
                  "(or are skipped). Installed packages stay installed."))
    if confirm_action(f"Install {', '.join(missing)} now?", default=True):
        print(fmt.dim("  Installing (this can take a minute)..."))
        ok, out = install_packages(missing)
        if ok:
            print(fmt.success(f"  Installed: {', '.join(missing)}"))
        else:
            tail = (out or '').strip().splitlines()[-1] if (out or '').strip() else 'no output'
            print(fmt.warning(f"  Install failed — continuing without. ({tail})"))
    return filter_missing(needed)


def report_environment():
    """Print what OS this is and which volume groups are being protected.

    Every distro-specific decision the simulator makes (which VG is the
    candidate's practice storage, which disk is the OS, where grub.cfg
    lives) is derived from this. Showing it at startup means a box we've
    mis-identified is visible immediately, instead of surfacing later as a
    task that behaved strangely. Best-effort — never fails the launch.
    """
    try:
        from utils import system_id
        findings = system_id.check_environment()
    except Exception:
        return

    for level, message in findings:
        if level == 'error':
            print(fmt.error(f"\n! {message}"))
        elif level == 'warn':
            print(fmt.warning(f"\n! {message}"))
        else:
            print(fmt.dim(f"  {message}"))


def warn_missing(missing=None):
    """Print a one-time warning listing missing packages and how to install
    them. No-op if nothing is missing (or rpm status is unknown)."""
    missing = missing if missing is not None else missing_packages()
    if not missing:
        return
    print(fmt.warning(
        f"\n! {len(missing)} exam-relevant package(s) not installed: {', '.join(missing)}"
    ))
    for pkg in missing:
        print(fmt.dim(f"    {pkg} — {required_packages().get(pkg, '')}"))
    print(fmt.warning(
        "  Tasks that rely on them may fail to set up their scenario "
        "(e.g. an httpd task where httpd never runs).\n"
        f"  Install with: dnf install -y {' '.join(missing)}\n"
    ))
