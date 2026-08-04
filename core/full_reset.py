"""
Full system reset — return a RHEL box to a near-blank, exam-ready state.

Unlike the lighter "System Reset" (which removes only known practice
artifacts), this strips the machine of the extra software and configuration a
box accumulates — third-party DNF repos, Flatpak apps/remotes, leftover lab
files, practice users, scheduled jobs, autofs maps, tuned changes, NFS exports
— so what remains is a basic RHEL install.

Deliberately PRESERVED (never touched here):
  * the rhcsa-simulator itself (its repo directory and data)
  * GitHub/SSH connectivity: ~/.config/gh, ~/.ssh, git config, and the
    subscription-manager RHEL system repos (rhel-*, redhat-*, redhat.repo)
  * networking, firewall, SELinux, and the system disk / system swap
  * login users below UID 1000 and any non-practice accounts

Everything is best-effort and guarded: one failing step never aborts the rest.
"""

import os
import re
import shutil
import subprocess

logger_prefix = "full_reset"

# The simulator's own tree — must survive the reset.
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# RHEL system repo files kept as-is (managed by subscription-manager).
_KEEP_REPO_FILES = {'redhat.repo'}
_KEEP_REPO_PREFIXES = ('rhel-', 'redhat-')

# Practice user/group name patterns — must mirror the generators in tasks/.
# Prefix + 1-2 digit suffix, or a small set of fixed names. Never matches a
# plain word without the numeric/fixed marker, so real accounts are safe.
_USER_PAT_NUMBERED = re.compile(
    r'^('
    r'alice|bob|carol|dave|eve|frank|grace|hank|'
    r'anna|ben|clara|dan|ella|finn|gina|hugo|iris|jake|'
    r'staffuser|ageuser|operator|locktest|removeuser|shelluser|troubleuser|'
    r'(?:nginx|redis|tomcat|grafana|prometheus|elasticsearch|kafka|rabbitmq|consul|vault)svc|'
    r'appsvc|mailsvc|websvc|dbsvc|ftpsvc|logsvc|'
    r'loginuser|sudouser|'
    r'user'
    r')\d{1,2}$'
)
_USER_PAT_FIXED = re.compile(r'^sudopractice$')
_GROUP_PAT = re.compile(
    r'^(devteam|qagroup|opsgroup|infrateam|secteam|datateam|cloudops)\d{2}$'
)

# fstab lines that belong to practice artifacts (removed with a backup kept).
_FSTAB_PATTERNS = [
    re.compile(r'/var/lib/rhcsa-simulator/loops/'),
    re.compile(r'/dev/loop\d+'),
    re.compile(r'\s/swapfile\b'),
    re.compile(r'\s/var/swap\b'),
    re.compile(r'\s/swap\.img\b'),
    re.compile(r'\s/tmp/swap\S*'),
    re.compile(r'\s/opt/swap\S*'),
    re.compile(r'RHCSA-FAULT'),
]


def _run(cmd, timeout=180):
    """Run a command, returning (rc, combined_output). Never raises."""
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return r.returncode, ((r.stdout or '') + (r.stderr or '')).strip()
    except FileNotFoundError:
        return 127, '(command not found)'
    except subprocess.TimeoutExpired:
        return 124, '(timed out)'
    except Exception as e:  # pragma: no cover - defensive
        return 1, f'(error: {e})'


def _noop(_msg):
    pass


# ── Repos ────────────────────────────────────────────────────────────────────

def list_nondefault_repos():
    """Third-party .repo files under /etc/yum.repos.d (RHEL system repos kept)."""
    # Task-created repo files are removable even when their name collides with
    # a protected system prefix (older task builds generated rhel-baseos/
    # rhel-appstream; real RHEL repos only ever live in redhat.repo).
    try:
        from core.lab_cleanup import _PRACTICE_REPO_SET
    except Exception:
        _PRACTICE_REPO_SET = set()
    out, d = [], '/etc/yum.repos.d'
    try:
        for f in sorted(os.listdir(d)):
            if not f.endswith('.repo'):
                continue
            full = os.path.join(d, f)
            if full not in _PRACTICE_REPO_SET and (
                    f in _KEEP_REPO_FILES or f.startswith(_KEEP_REPO_PREFIXES)):
                continue
            out.append(full)
    except Exception:
        pass
    return out


def remove_repos(progress=_noop):
    repos = list_nondefault_repos()
    removed = 0
    for rf in repos:
        try:
            os.remove(rf)
            removed += 1
            progress(f"  removed repo {os.path.basename(rf)}")
        except OSError as e:
            progress(f"  could not remove {rf}: {e}")
    if not repos:
        progress("  no third-party repos")
    return removed


# ── Flatpak ──────────────────────────────────────────────────────────────────

def flatpak_available():
    return shutil.which('flatpak') is not None


def _flatpak_column(kind):
    """Return names from `flatpak <kind> --columns=…`, header-stripped."""
    if kind == 'apps':
        rc, out = _run(['flatpak', 'list', '--app', '--columns=application'])
    else:
        rc, out = _run(['flatpak', 'remotes', '--columns=name'])
    if rc != 0:
        return []
    names = []
    for line in out.splitlines():
        s = line.strip()
        if not s or s.lower() in ('application', 'name'):
            continue
        names.append(s.split()[0])
    return names


def list_flatpak_apps():
    return _flatpak_column('apps') if flatpak_available() else []


def list_flatpak_remotes():
    return _flatpak_column('remotes') if flatpak_available() else []


def remove_flatpak(progress=_noop):
    """Uninstall every Flatpak app + unused runtimes, then drop all remotes."""
    if not flatpak_available():
        progress("  flatpak not installed")
        return 0
    count = 0
    apps = list_flatpak_apps()
    for app in apps:
        rc, out = _run(['flatpak', 'uninstall', '-y', '--noninteractive', app])
        if rc == 0:
            count += 1
            progress(f"  uninstalled app {app}")
        else:
            progress(f"  could not uninstall {app}: {out.splitlines()[-1] if out else rc}")
    # Remove now-unused runtimes/extensions left behind.
    _run(['flatpak', 'uninstall', '-y', '--unused', '--noninteractive'])
    for remote in list_flatpak_remotes():
        rc, _ = _run(['flatpak', 'remote-delete', '--force', remote])
        if rc == 0:
            progress(f"  removed remote {remote}")
    return count


# ── DNF cache ────────────────────────────────────────────────────────────────

def clean_dnf(progress=_noop):
    rc, _ = _run(['dnf', 'clean', 'all'])
    progress("  dnf cache cleaned" if rc == 0 else "  dnf clean reported an error")
    return rc == 0


# ── /usr/local/bin scripts ───────────────────────────────────────────────────

def list_local_scripts():
    d = '/usr/local/bin'
    try:
        return [os.path.join(d, f) for f in os.listdir(d)
                if f.endswith('.sh') and os.path.isfile(os.path.join(d, f))]
    except Exception:
        return []


def remove_local_scripts(progress=_noop):
    removed = 0
    for s in list_local_scripts():
        try:
            os.remove(s)
            removed += 1
            progress(f"  removed script {s}")
        except OSError as e:
            progress(f"  could not remove {s}: {e}")
    return removed


# ── Scheduled work ───────────────────────────────────────────────────────────

def clear_scheduled(progress=_noop):
    # root crontab
    rc, out = _run(['crontab', '-l', '-u', 'root'])
    if rc == 0 and out.strip():
        _run(['crontab', '-r', '-u', 'root'])
        progress("  cleared root crontab")
    # at jobs
    rc, out = _run(['atq'])
    if rc == 0 and out.strip():
        for line in out.splitlines():
            parts = line.split()
            if parts:
                _run(['atrm', parts[0]])
        progress("  removed pending at jobs")


# ── Tuned ────────────────────────────────────────────────────────────────────

def reset_tuned(progress=_noop):
    rc, rec = _run(['tuned-adm', 'recommend'])
    profile = rec.strip() if rc == 0 and rec.strip() else 'balanced'
    rc, _ = _run(['tuned-adm', 'profile', profile])
    if rc == 0:
        progress(f"  tuned profile reset to '{profile}'")


# ── Autofs ───────────────────────────────────────────────────────────────────

def clean_autofs(progress=_noop):
    changed = False
    if _run(['systemctl', 'is-active', '--quiet', 'autofs'])[0] == 0:
        _run(['systemctl', 'stop', 'autofs'])
    # auto.master non-default lines
    auto_master = '/etc/auto.master'
    defaults = {'+dir:/etc/auto.master.d', '+auto.master'}
    try:
        with open(auto_master) as f:
            lines = f.readlines()
        keep = [ln for ln in lines
                if not ln.strip() or ln.strip().startswith('#')
                or ln.strip() in defaults]
        if len(keep) != len(lines):
            with open(auto_master, 'w') as f:
                f.writelines(keep)
            changed = True
            progress("  cleaned /etc/auto.master")
    except FileNotFoundError:
        pass
    except Exception as e:
        progress(f"  auto.master error: {e}")
    # drop-ins + extra maps
    for di in _glob('/etc/auto.master.d/*.autofs'):
        try:
            os.remove(di); changed = True; progress(f"  removed {di}")
        except OSError:
            pass
    try:
        for f in os.listdir('/etc'):
            if (f.startswith('auto.') and f not in
                    ('auto.master', 'auto.misc', 'auto.master.d')
                    and os.path.isfile(f'/etc/{f}')):
                os.remove(f'/etc/{f}'); changed = True
                progress(f"  removed /etc/{f}")
    except Exception:
        pass
    return changed


def _glob(pattern):
    import glob
    return glob.glob(pattern)


# ── Practice users / groups ──────────────────────────────────────────────────

def _is_practice_user(name):
    return bool(_USER_PAT_NUMBERED.match(name) or _USER_PAT_FIXED.match(name))


def list_practice_users():
    users = []
    try:
        import pwd
        for pw in pwd.getpwall():
            if pw.pw_uid >= 1000 and _is_practice_user(pw.pw_name):
                users.append(pw.pw_name)
    except Exception:
        pass
    return users


def list_practice_groups():
    groups = []
    try:
        import grp
        for gr in grp.getgrall():
            if gr.gr_gid >= 1000 and _GROUP_PAT.match(gr.gr_name):
                groups.append(gr.gr_name)
    except Exception:
        pass
    return groups


def remove_practice_users_groups(progress=_noop):
    n = 0
    for u in list_practice_users():
        _run(['userdel', '-r', u])
        n += 1
        progress(f"  deleted user {u}")
    for g in list_practice_groups():
        _run(['groupdel', g])
        progress(f"  deleted group {g}")
    return n


# ── Unmount everything practice-related ──────────────────────────────────────

# Never unmount these — the OS/login/simulator depend on them.
_PROTECTED_TARGETS = {
    '/', '/boot', '/boot/efi', '/home', '/var', '/usr', '/opt', '/etc',
    '/proc', '/sys', '/run', '/dev', '/dev/shm', '/tmp', '/var/tmp',
}
_PROTECTED_PREFIXES = ('/proc', '/sys', '/run', '/dev', '/boot', '/usr',
                       '/var/lib/nfs', '/etc')
# Targets where exam/practice filesystems get mounted.
_PRACTICE_TARGET_PREFIXES = ('/mnt/', '/media/', '/srv/', '/data', '/export',
                             '/shares', '/misc/', '/autofs')

# System volume groups whose LVs must never be unmounted. Detected from the
# live mounts (see utils.system_id), with a static name list as fallback.
try:
    from utils.system_id import KNOWN_SYSTEM_VG_NAMES as _SYS_VGS
    from utils.system_id import is_system_vg
except Exception:  # pragma: no cover - fallback if system_id is unavailable
    _SYS_VGS = {'rl', 'rl00', 'rhel', 'centos', 'fedora', 'almalinux', 'rocky'}

    def is_system_vg(vg):
        return not vg or vg.strip() in _SYS_VGS


def _dm_vg(source):
    """Extract the VG name from a /dev/mapper/vg-lv or /dev/dm-* source."""
    name = source.rsplit('/', 1)[-1]
    # device-mapper doubles literal dashes; split on a single dash only.
    vg = re.split(r'(?<!-)-(?!-)', name)[0].replace('--', '-')
    return vg


def _is_practice_mount(target, source, fstype):
    if target in _PROTECTED_TARGETS or target.startswith(_PROTECTED_PREFIXES):
        return False
    if target == REPO_ROOT or target.startswith(REPO_ROOT + '/'):
        return False
    if fstype in ('nfs', 'nfs4'):
        return True
    if re.match(r'^/dev/loop\d+', source or ''):
        return True
    if (source or '').startswith(('/dev/mapper/', '/dev/dm-')):
        return not is_system_vg(_dm_vg(source))
    if target.startswith(_PRACTICE_TARGET_PREFIXES):
        return True
    return False


def list_practice_mounts():
    """Return [(target, source, fstype)] for non-system mounts, deepest first."""
    rc, out = _run(['findmnt', '-rno', 'TARGET,SOURCE,FSTYPE'], timeout=15)
    if rc != 0:
        return []
    mounts = []
    for line in out.splitlines():
        parts = line.split()
        if len(parts) < 3:
            continue
        target, source, fstype = parts[0], parts[1], parts[2]
        if _is_practice_mount(target, source, fstype):
            mounts.append((target, source, fstype))
    # Unmount the deepest paths first so nested mounts come off cleanly.
    mounts.sort(key=lambda m: m[0].count('/'), reverse=True)
    return mounts


def unmount_practice_mounts(progress=_noop):
    """Unmount all exam/practice mounts (NFS, loop/LVM filesystems, practice
    mount points) before disks are torn down. NFS goes straight to force+lazy so
    a stale server can't hang us; others try a clean umount then fall back."""
    mounts = list_practice_mounts()
    n = 0
    for target, source, fstype in mounts:
        if fstype in ('nfs', 'nfs4'):
            rc, _ = _run(['umount', '-f', '-l', '--', target], timeout=30)
        else:
            rc, _ = _run(['umount', '--', target], timeout=30)
            if rc != 0:
                rc, _ = _run(['umount', '-l', '--', target], timeout=30)
        if rc == 0:
            n += 1
            progress(f"  unmounted {target} ({fstype} <- {source})")
        else:
            progress(f"  could not unmount {target}")
    if not mounts:
        progress("  no practice mounts active")
    return n


# ── Practice swap + fstab ────────────────────────────────────────────────────

def _system_swap(device):
    """True for the swap the OS installed itself, which must survive a reset.

    Name matching alone ('rhel' in the path) only recognised RHEL's own
    layout; an AlmaLinux swap partition on /dev/sda3 looked like practice
    swap and got torn out of fstab. Ask what the device actually is first.
    """
    try:
        from utils.system_id import is_system_disk, vg_of_device, is_system_vg
        vg = vg_of_device(device)
        if vg:
            return is_system_vg(vg)
        if is_system_disk(device):
            return True
    except Exception:
        pass
    return any(x in device for x in ('/dev/nvme', 'rhel', 'dm-'))


def remove_practice_swap(progress=_noop):
    entries = []
    try:
        with open('/proc/swaps') as f:
            for line in f.readlines()[1:]:
                parts = line.split()
                if len(parts) >= 2 and not _system_swap(parts[0]):
                    entries.append((parts[0], parts[1]))
    except Exception:
        pass
    for device, stype in entries:
        _run(['swapoff', device])
        if stype == 'file' and os.path.exists(device):
            try:
                os.remove(device)
                progress(f"  removed swap file {device}")
            except OSError:
                pass
        else:
            progress(f"  deactivated swap {device}")
    return len(entries)


def clean_fstab(progress=_noop):
    """Strip practice lines from /etc/fstab, keeping a one-shot backup."""
    try:
        with open('/etc/fstab') as f:
            lines = f.readlines()
    except Exception:
        return False
    keep, dropped = [], 0
    for line in lines:
        s = line.strip()
        if not s or s.startswith('#'):
            keep.append(line); continue
        if any(p.search(line) for p in _FSTAB_PATTERNS):
            dropped += 1
        else:
            keep.append(line)
    if dropped:
        try:
            shutil.copy2('/etc/fstab', '/etc/fstab.rhcsa-bak')
            with open('/etc/fstab', 'w') as f:
                f.writelines(keep)
            progress(f"  removed {dropped} practice fstab line(s) (backup: /etc/fstab.rhcsa-bak)")
        except Exception as e:
            progress(f"  fstab cleanup error: {e}")
            return False
    return dropped > 0


# ── Preview + orchestration ──────────────────────────────────────────────────

def preview():
    """Return a dict of enumerable things this reset would remove, for a
    confirmation screen. Non-enumerable steps (dnf clean, tuned) are omitted."""
    from core import lab_cleanup
    data = {
        'Active mounts to unmount': [f"{t}  ({fs})" for t, s, fs in list_practice_mounts()],
        'Third-party repos': list_nondefault_repos(),
        'Flatpak apps': list_flatpak_apps(),
        'Flatpak remotes': list_flatpak_remotes(),
        'Scripts (/usr/local/bin)': list_local_scripts(),
        'Practice users': list_practice_users(),
        'Practice groups': list_practice_groups(),
    }
    try:
        data['Lab files/dirs'] = lab_cleanup.clean(dry_run=True)
    except Exception:
        data['Lab files/dirs'] = []
    return data


def run_all(progress=_noop, remove_users=True):
    """Execute the full reset. Returns a summary dict. Never raises."""
    summary = {}

    def step(name, fn):
        progress("")
        progress(name)
        try:
            summary[name] = fn()
        except Exception as e:
            progress(f"  step failed: {e}")
            summary[name] = None

    # 0. Unmount every exam/practice mount first (NFS, loop/LVM filesystems,
    #    practice mount points) so later steps aren't blocked by busy devices.
    step("Unmount practice mounts", lambda: unmount_practice_mounts(progress))

    # 1. Known lab artifacts (files, dirs, mounts).
    def _lab():
        from core import lab_cleanup
        done = lab_cleanup.clean(dry_run=False)
        progress(f"  removed {len(done)} lab artifact(s)")
        return len(done)
    step("Lab leftover files", _lab)

    # 2. Practice disks / LVM (loop images + structures).
    def _disks():
        from utils import helpers
        # Unmount any mounted loop partitions first.
        rc, out = _run(['lsblk', '-rno', 'NAME,MOUNTPOINT'])
        for line in out.splitlines():
            parts = line.split()
            if len(parts) == 2 and 'loop' in parts[0] and parts[1].startswith('/'):
                _run(['umount', '-f', f"/dev/{parts[0]}"])
        ok = helpers.cleanup_practice_devices()
        progress("  practice disks removed" if ok else "  no practice disks / cleanup errors")
        return ok
    step("Practice disks / LVM", _disks)

    # 3. Practice swap + fstab.
    step("Practice swap", lambda: remove_practice_swap(progress))
    step("fstab cleanup", lambda: clean_fstab(progress))

    # 4. Third-party repos + dnf cache.
    step("Third-party DNF repos", lambda: remove_repos(progress))
    step("DNF cache", lambda: clean_dnf(progress))

    # 5. Flatpak apps + remotes.
    step("Flatpak apps / remotes", lambda: remove_flatpak(progress))

    # 6. Scripts, scheduled work, tuned, autofs.
    step("Scripts in /usr/local/bin", lambda: remove_local_scripts(progress))
    step("Scheduled jobs (cron/at)", lambda: clear_scheduled(progress))
    step("Tuned profile", lambda: reset_tuned(progress))
    step("Autofs maps", lambda: clean_autofs(progress))

    # 7. Remote NFS exports we provisioned.
    def _nfs():
        try:
            from core import nfs_server
            if not nfs_server.load_config():
                progress("  no NFS server configured")
                return 0
            n = nfs_server.unmount_client_mounts()
            nfs_server.remove_exports()
            progress(f"  NFS exports removed (unmounted {n} client mount(s))")
            return 1
        except Exception as e:
            progress(f"  NFS teardown error: {e}")
            return 0
    step("Remote NFS exports", _nfs)

    # 7b. Active boot-rescue scenario: put the lab machine's root password back.
    def _rescue():
        from core import boot_rescue
        boot_rescue.reset_for_machine_reset(progress)
        return 1
    step("Boot-rescue scenario", _rescue)

    # 8. Practice users / groups (optional).
    if remove_users:
        step("Practice users / groups",
             lambda: remove_practice_users_groups(progress))

    # 9. Restore any active troubleshooting fault.
    def _fault():
        try:
            from tasks.troubleshooting import restore_any_active_fault
            had, msg = restore_any_active_fault()
            if had:
                progress(f"  restored: {msg}")
            return had
        except Exception:
            return False
    step("Active fault restore", _fault)

    return summary
