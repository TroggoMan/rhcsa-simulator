"""
Troubleshooting tasks for RHCSA Simulator.

Each task injects a real fault onto the system, lets the user diagnose
and fix it, then restores the system regardless of outcome.

inject_fault()   — breaks the system (called before showing the task)
restore_fault()  — restores original state (called after validate or skip)

Active faults are recorded in FAULT_STATE_FILE so system_reset() can
always restore even if the simulator crashes mid-task.
"""

import json
import logging
import os
import random
import subprocess

from tasks.base import BaseTask
from tasks.registry import TaskRegistry
from core.validator import ValidationCheck, ValidationResult
from validators.safe_executor import execute_safe

logger = logging.getLogger(__name__)

FAULT_STATE_FILE = '/var/lib/rhcsa-simulator/active_fault.json'


# ── Fault-state bookkeeping ───────────────────────────────────────────────────

def _read_faults() -> dict:
    """Return {task_id: restore_info} for all active faults (migrates legacy)."""
    try:
        with open(FAULT_STATE_FILE) as f:
            data = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}
    if isinstance(data, dict) and 'faults' in data and isinstance(data['faults'], dict):
        return data['faults']
    # Legacy single-entry format: {'task_id':..., 'restore_info':...}
    if isinstance(data, dict) and 'task_id' in data:
        return {data['task_id']: data.get('restore_info', {})}
    return {}


def _write_faults(faults: dict):
    if faults:
        os.makedirs(os.path.dirname(FAULT_STATE_FILE), exist_ok=True)
        with open(FAULT_STATE_FILE, 'w') as f:
            json.dump({'faults': faults}, f)
    else:
        try:
            os.remove(FAULT_STATE_FILE)
        except FileNotFoundError:
            pass


def save_fault_state(task_id: str, restore_info: dict):
    """Record an active fault. Multiple concurrent faults are kept, keyed by
    task_id, so exam tasks that inject in parallel don't clobber each other."""
    faults = _read_faults()
    faults[task_id] = restore_info
    _write_faults(faults)


def load_fault_state(task_id: str = None) -> dict | None:
    """Return {'task_id', 'restore_info'} for the given task (or any one fault
    when task_id is None, for the startup 'stale fault' warning)."""
    faults = _read_faults()
    if not faults:
        return None
    if task_id is None:
        task_id = next(iter(faults))
    elif task_id not in faults:
        return None
    return {'task_id': task_id, 'restore_info': faults[task_id]}


def clear_fault_state(task_id: str = None):
    """Clear one fault (task_id given) or all faults (task_id None)."""
    if task_id is None:
        _write_faults({})
        return
    faults = _read_faults()
    faults.pop(task_id, None)
    _write_faults(faults)


def get_active_faults() -> dict:
    """All active faults as {task_id: restore_info}."""
    return _read_faults()


def restore_any_active_fault():
    """Called at startup and during system_reset to restore stale fault(s)."""
    faults = _read_faults()
    if not faults:
        return False, "No active fault"
    msgs = []
    for task_id, info in list(faults.items()):
        _dispatch_restore(task_id, info, msgs)
    clear_fault_state()
    return True, '\n'.join(msgs)


def _restore_remote(info, msgs):
    """Undo a remote task's change on the linked lab machine (best-effort —
    the machine may be down; the record is cleared either way, matching how
    unreachable local restores behave)."""
    from core import lab_machine
    label = info.get('label', 'remote task')
    host = lab_machine.get_host() or 'lab machine'
    rc, _ = lab_machine.run(info['remote_restore_script'], timeout=60)
    if rc == 0:
        msgs.append(f"Restored {label} on {host}")
    else:
        msgs.append(f"Could not restore {label} on {host} (unreachable?)")


def _dispatch_restore(task_id, info, msgs):
    """Restore a single fault by task_id (crash-recovery dispatcher)."""
    # Generic environment-setup records (from positive-config tasks that
    # establish a negative precondition at exam start) carry a restore_type and
    # are undone independently of their task_id.
    if isinstance(info, dict) and info.get('restore_type'):
        _restore_env_setup(info, msgs)
        return
    # Remote-task records: the restore runs on the linked lab machine.
    if isinstance(info, dict) and info.get('remote_restore_script'):
        _restore_remote(info, msgs)
        return
    # Dispatch to the right restorer
    if task_id.startswith('fault_selinux_context'):
        _restore_selinux_context(info, msgs)
    elif task_id.startswith('fault_selinux_boolean'):
        _restore_selinux_boolean(info, msgs)
    elif task_id.startswith('fault_firewall'):
        _restore_firewall(info, msgs)
    elif task_id.startswith('fault_sshd_config'):
        _restore_sshd_config(info, msgs)
    elif task_id.startswith('fault_service'):
        _restore_service(info, msgs)
    elif task_id.startswith('fault_sudoers'):
        _restore_sudoers_full(info, msgs)
    elif task_id.startswith('fault_fstab') or task_id == 'boot_fstab_validate_001':
        _restore_fstab(info, msgs)
    elif (task_id.startswith('time_ntp') or task_id.startswith('time_chrony')
          or task_id.startswith('time_pool') or task_id == 'time_set_001'):
        _restore_time_sync(info, msgs)
    elif task_id.startswith('fw_enable') or task_id == 'fw_enable_001':
        _restore_service(info, msgs)
    elif task_id == 'fw_reload_001':
        svc = info.get('service', 'tftp')
        subprocess.run(['firewall-cmd', '--permanent', '--remove-service', svc], capture_output=True)
        subprocess.run(['firewall-cmd', '--remove-service', svc], capture_output=True)
        msgs.append(f"Removed injected firewall service '{svc}'")
    elif task_id == 'boot_kernel_param_remove_001':
        param = info.get('parameter', '')
        if param:
            subprocess.run(['grubby', '--remove-args', param, '--update-kernel=ALL'], capture_output=True)
            msgs.append(f"Removed injected kernel parameter '{param}'")
    elif task_id == 'fs_extend_001':
        vg = info.get('vg', 'vg_practice')
        lv = info.get('lv', 'lv_practice')
        pv = info.get('pv', '')
        mp = info.get('mp', '/mnt/practice_extend')
        subprocess.run(['umount', mp], capture_output=True)
        subprocess.run(['lvremove', '-ff', f'/dev/{vg}/{lv}'], capture_output=True)
        subprocess.run(['vgchange', '-an', vg], capture_output=True)
        subprocess.run(['vgremove', '-ff', vg], capture_output=True)
        if pv:
            subprocess.run(['pvremove', '-ff', '-y', pv], capture_output=True)
        msgs.append(f"Cleaned up practice LVM ({vg}/{lv}) and {mp}")
    elif task_id == 'lvm_vg_extend_001':
        vg = info.get('vg', 'vg_practice')
        subprocess.run(['vgchange', '-an', vg], capture_output=True)
        subprocess.run(['vgremove', '-ff', vg], capture_output=True)
        for dev in filter(None, [info.get('base_dev'), info.get('new_dev')]):
            subprocess.run(['pvremove', '-ff', '-y', dev], capture_output=True)
        msgs.append(f"Cleaned up VG {vg}")
    elif task_id == 'journalctl_persistent_journal_001':
        import shutil as _shutil
        backup = info.get('backup', '/var/lib/rhcsa-simulator/journald.conf.bak')
        if os.path.exists(backup):
            _shutil.copy2(backup, '/etc/systemd/journald.conf')
            os.remove(backup)
        subprocess.run(['systemctl', 'restart', 'systemd-journald'], capture_output=True)
        msgs.append("Restored journald.conf")
    elif task_id == 'boot_troubleshoot_001':
        orig_target = info.get('orig_target', 'multi-user.target')
        subprocess.run(['systemctl', 'set-default', orig_target], capture_output=True)
        added_param = info.get('added_param')
        removed_param = info.get('removed_param')
        if added_param:
            subprocess.run(['grubby', '--remove-args', added_param, '--update-kernel=ALL'], capture_output=True)
        if removed_param:
            subprocess.run(['grubby', '--args', removed_param, '--update-kernel=ALL'], capture_output=True)
        grub_cfg = info.get('grub_cfg', '/boot/grub2/grub.cfg')
        subprocess.run(['grub2-mkconfig', '-o', grub_cfg], capture_output=True)
        msgs.append(f"Restored boot config (target={orig_target})")
    elif task_id.startswith('net_hostname'):
        orig = info.get('orig_hostname', '')
        if orig:
            subprocess.run(['hostnamectl', 'set-hostname', orig],
                           capture_output=True)
            msgs.append(f"Restored hostname to {orig}")
    elif task_id == 'net_full_setup_001':
        iface = info.get('iface', 'dummy0')
        conn = info.get('conn', 'practice-net')
        orig_hostname = info.get('orig_hostname', '')
        subprocess.run(['nmcli', 'con', 'delete', conn], capture_output=True)
        subprocess.run(['ip', 'link', 'delete', iface], capture_output=True)
        if orig_hostname:
            subprocess.run(['hostnamectl', 'set-hostname', orig_hostname], capture_output=True)
        msgs.append(f"Cleaned up {iface} and {conn}")
    elif task_id == 'proc_kill_001':
        name = info.get('process')
        d = info.get('dir')
        if name:
            subprocess.run(['pkill', '-x', name], capture_output=True)
        if d:
            import shutil as _sh
            _sh.rmtree(d, ignore_errors=True)
        msgs.append(f"Killed injected '{name}' processes")
    elif task_id == 'proc_find_user_001':
        user = info.get('username', 'apache')
        subprocess.run(['pkill', '-u', user], capture_output=True)
        if info.get('created_user'):
            subprocess.run(['userdel', '-rf', user], capture_output=True)
        msgs.append(f"Cleaned up processes for user '{user}'")
    elif task_id.startswith('selinux_denial'):
        import shutil as _sh
        directory = info.get('directory')
        if directory and os.path.exists(directory):
            subprocess.run(['restorecon', '-Rv', directory], capture_output=True)
            _sh.rmtree(directory, ignore_errors=True)
        msgs.append(f"Removed injected SELinux practice dir {directory}")
    elif (task_id.startswith('lvm_lv_') or task_id.startswith('lvm_extend')
          or {'vg', 'dev'} <= set(info.keys())):
        vg = info.get('vg')
        dev = info.get('dev')
        if vg:
            subprocess.run(['lvremove', '-ff', vg], capture_output=True)
            subprocess.run(['vgchange', '-an', vg], capture_output=True)
            subprocess.run(['vgremove', '-ff', vg], capture_output=True)
        if dev:
            subprocess.run(['pvremove', '-ff', '-y', dev], capture_output=True)
            subprocess.run(['wipefs', '-a', dev], capture_output=True)
        msgs.append(f"Cleaned up scratch LVM ({vg})")
    else:
        msgs.append(f"Unknown fault type: {task_id}")


# ── Shared restore helpers ────────────────────────────────────────────────────

def _run(cmd, timeout=15):
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)


def _restore_selinux_context(info, msgs):
    path = info.get('path')
    if path:
        r = _run(['restorecon', '-Rv', path])
        msgs.append(f"restorecon {path}: {'ok' if r.returncode == 0 else r.stderr.strip()}")


def _restore_selinux_boolean(info, msgs):
    name = info.get('boolean')
    original = info.get('original_value', 'on')
    if name:
        r = _run(['setsebool', '-P', name, original])
        msgs.append(f"setsebool -P {name} {original}: {'ok' if r.returncode == 0 else r.stderr.strip()}")


def _restore_firewall(info, msgs):
    zone = info.get('zone', 'public')
    svc = info.get('service')
    port = info.get('port')
    if svc:
        _run(['firewall-cmd', f'--zone={zone}', f'--add-service={svc}'])
        _run(['firewall-cmd', f'--zone={zone}', f'--add-service={svc}', '--permanent'])
        msgs.append(f"Restored firewall service {svc} in zone {zone}")
    if port:
        _run(['firewall-cmd', f'--zone={zone}', f'--add-port={port}'])
        _run(['firewall-cmd', f'--zone={zone}', f'--add-port={port}', '--permanent'])
        msgs.append(f"Restored firewall port {port} in zone {zone}")


def _restore_sshd_config(info, msgs):
    marker = info.get('marker', '')
    if marker:
        with open('/etc/ssh/sshd_config', 'r') as f:
            lines = f.readlines()
        cleaned = [l for l in lines if marker not in l]
        with open('/etc/ssh/sshd_config', 'w') as f:
            f.writelines(cleaned)
        msgs.append("Removed injected sshd_config line")
    # Restart sshd only if it's not already running
    r = _run(['systemctl', 'is-active', '--quiet', 'sshd'])
    if r.returncode != 0:
        _run(['systemctl', 'start', 'sshd'])
        msgs.append("Restarted sshd")


def _restore_service(info, msgs):
    name = info.get('service')
    was_active = info.get('was_active', True)
    was_enabled = info.get('was_enabled', True)
    if name:
        if was_active:
            _run(['systemctl', 'start', name])
        if was_enabled:
            _run(['systemctl', 'enable', name])
        msgs.append(f"Restored {name} service state")


def _restore_sudoers(info, msgs):
    path = info.get('path')
    original_perms = info.get('original_perms', '0440')
    if path and os.path.exists(path):
        os.chmod(path, int(original_perms, 8))
        msgs.append(f"Restored {path} permissions to {original_perms}")


_SUDOERS_PRACTICE_USER = 'sudopractice'
_SUDOERS_PRACTICE_FILE = '/etc/sudoers.d/sudopractice'


def _restore_sudoers_full(info, msgs):
    """Full crash-recovery restore: remove the practice sudoers file and user."""
    path = info.get('path', _SUDOERS_PRACTICE_FILE)
    user = info.get('user', _SUDOERS_PRACTICE_USER)
    if os.path.exists(path):
        os.remove(path)
        msgs.append(f"Removed {path}")
    r = _run(['id', user])
    if r.returncode == 0:
        _run(['userdel', user])
        msgs.append(f"Removed practice user {user}")


def _restore_time_sync(info, msgs):
    """Restore chronyd/NTP state broken by the time-sync fault injectors."""
    import time
    import datetime

    # Reset the clock first if a manual-set task may have moved it. With no
    # network NTP to ask, the best available estimate of "now" is the wall
    # clock captured at injection (while it was still correct) plus the
    # monotonic time elapsed since — CLOCK_MONOTONIC isn't affected by the
    # candidate's clock changes. (After a real reboot monotonic restarts, so
    # this degrades to the injection-time clock — still far closer than the
    # arbitrary target time the task had the candidate set.)
    iw = info.get('injected_wallclock')
    im = info.get('injected_monotonic')
    if iw is not None and im is not None:
        real_now = iw + max(0.0, time.monotonic() - im)
        if abs(time.time() - real_now) > 5:
            ts = datetime.datetime.fromtimestamp(real_now).strftime(
                '%Y-%m-%d %H:%M:%S')
            _run(['timedatectl', 'set-ntp', 'false'])  # set-time needs NTP off
            _run(['timedatectl', 'set-time', ts])
            msgs.append(f"Reset system clock to {ts}")

    # Put chrony.conf back exactly as it was before the candidate's edits,
    # before (re)starting chronyd below so the daemon loads the original.
    conf = info.get('chrony_conf')
    if conf is not None:
        try:
            with open('/etc/chrony.conf', 'w') as f:
                f.write(conf)
            _run(['systemctl', 'try-restart', 'chronyd'])
            msgs.append("Restored /etc/chrony.conf")
        except OSError:
            pass

    if info.get('chronyd_was_enabled', True):
        _run(['systemctl', 'enable', 'chronyd'])
    if info.get('chronyd_was_active', True):
        _run(['systemctl', 'start', 'chronyd'])
    if info.get('ntp_was_on', True):
        _run(['timedatectl', 'set-ntp', 'true'])
    # If an NTP server is reachable, step the clock to true time immediately
    # instead of slewing for hours. Harmless no-op offline or if chronyd is
    # not running.
    _run(['chronyc', 'makestep'])
    msgs.append("Restored chronyd/NTP state")


def _restore_fstab(info, msgs):
    marker = info.get('marker', '')
    if marker:
        with open('/etc/fstab', 'r') as f:
            lines = f.readlines()
        cleaned = [l for l in lines if marker not in l]
        with open('/etc/fstab', 'w') as f:
            f.writelines(cleaned)
        msgs.append("Removed injected fstab line")


def _restore_env_setup(info, msgs):
    """Undo a positive-task environment setup (see tasks/env_setup.py)."""
    rt = info.get('restore_type')
    if rt == 'unit':
        unit = info.get('unit')
        if not unit:
            return
        if info.get('was_enabled'):
            subprocess.run(['systemctl', 'enable', unit], capture_output=True)
        else:
            subprocess.run(['systemctl', 'disable', unit], capture_output=True)
        if info.get('was_active'):
            subprocess.run(['systemctl', 'start', unit], capture_output=True)
        else:
            subprocess.run(['systemctl', 'stop', unit], capture_output=True)
        msgs.append(f"Restored {unit} (active={info.get('was_active')}, "
                    f"enabled={info.get('was_enabled')})")
    elif rt == 'file_backup':
        import shutil as _shutil
        for p in info.get('paths', []):
            bak = p + '.rhcsa-bak'
            if os.path.exists(bak):
                try:
                    _shutil.move(bak, p)
                except OSError:
                    pass
        msgs.append(f"Restored original file(s): {info.get('paths')}")
    elif rt == 'pkg_remove':
        pkg = info.get('pkg')
        if pkg:
            subprocess.run(['dnf', '-y', 'remove', pkg], capture_output=True)
            msgs.append(f"Removed setup package {pkg}")
    elif rt == 'pkg_install':
        pkg = info.get('pkg')
        if pkg:
            subprocess.run(['dnf', '-y', 'install', pkg], capture_output=True)
            msgs.append(f"Reinstalled package {pkg}")
    elif rt == 'flatpak_install':
        app = info.get('app_id')
        if app:
            subprocess.run(['flatpak', 'install', '-y', 'flathub', app], capture_output=True)
            msgs.append(f"Reinstalled flatpak {app}")


# ── httpd availability (RHEL/Rocky minimal installs don't ship httpd) ────────
#
# Several fault-injection tasks describe an "httpd is running but ..." symptom.
# Session prep OFFERS to install missing packages (tasks declare them via
# required_packages) — nothing is ever installed silently here. If httpd is
# still absent when a fault is injected, the task degrades: SELinux faults
# fabricate the log evidence a real denial would have left (see
# _seed_avc_denial), service/firewall faults fall back to descriptive-only.

def _httpd_pkg_key(task_id):
    return f'{task_id}__httpd_pkg'


def _httpd_svc_key(task_id):
    return f'{task_id}__httpd_svc'


def _httpd_present():
    """True if the httpd package is installed. Never installs anything."""
    return _run(['rpm', '-q', 'httpd']).returncode == 0


def _ensure_httpd_running(task_id):
    """Start+enable httpd if it isn't already (httpd must be installed first)."""
    from tasks.env_setup import make_service_present
    make_service_present(_httpd_svc_key(task_id), 'httpd')


def _restore_httpd_setup(task_id, msgs):
    """Undo whatever _ensure_httpd_running() did for this task (and replay any
    package record left by an older version) — service state first."""
    for key in (_httpd_svc_key(task_id), _httpd_pkg_key(task_id)):
        state = load_fault_state(key)
        if state:
            _restore_env_setup(state['restore_info'], msgs)
            clear_fault_state(key)


# ── Synthetic AVC evidence ────────────────────────────────────────────────────
#
# When a real denial can't be triggered (httpd not installed, so nothing ever
# hits the mislabelled file / blocked port), the candidate would find empty
# audit logs and the troubleshooting trail would go cold. In that case we write
# the same records a real denial would have produced — an AVC line into
# /var/log/audit/audit.log (so `ausearch -m AVC | audit2why` works) and a
# setroubleshoot-style journal entry — so the documented diagnosis path still
# leads to the root cause.

_AUDIT_LOG = '/var/log/audit/audit.log'


def _seed_avc_denial(avc_body, journal_msg):
    """Append one AVC record to the audit log and mirror it to the journal.
    Best-effort: failures are silent (the fault itself is still in place)."""
    import time as _time
    import random as _random
    ts = f"{_time.time():.3f}"
    serial = _random.randint(9000, 99999)
    line = f"type=AVC msg=audit({ts}:{serial}): avc:  denied  {avc_body}\n"
    try:
        existed = os.path.exists(_AUDIT_LOG)
        os.makedirs(os.path.dirname(_AUDIT_LOG), exist_ok=True)
        with open(_AUDIT_LOG, 'a') as f:
            f.write(line)
        if not existed:
            os.chmod(_AUDIT_LOG, 0o600)
    except OSError:
        pass
    try:
        _run(['logger', '-p', 'daemon.err', '-t', 'setroubleshoot', journal_msg],
             timeout=10)
    except Exception:
        pass


# ── Base class ────────────────────────────────────────────────────────────────

class TroubleshootingTask(BaseTask):
    """
    Base for tasks that actually inject a fault before the user works on it.
    Subclasses must implement inject_fault() and restore_fault().
    """
    has_fault_injection = True

    def __init__(self, id, category, difficulty, points):
        super().__init__(id=id, category=category, difficulty=difficulty, points=points)

    def inject_fault(self) -> tuple:
        """Break the system. Returns (success: bool, message: str)."""
        return True, "No fault configured"

    def restore_fault(self) -> tuple:
        """Restore original state. Returns (success: bool, message: str)."""
        return True, "Nothing to restore"


# ── SELinux: wrong file context on web root ───────────────────────────────────

@TaskRegistry.register("troubleshooting")
class SELinuxHttpdContextFaultTask(TroubleshootingTask):

    required_packages = ['httpd']

    def __init__(self):
        super().__init__(
            id="fault_selinux_context_httpd_001",
            category="troubleshooting",
            difficulty="exam",
            points=14
        )
        self.web_root = '/var/www/html'
        self.exam_domain = 7
        self.tags = ['selinux', 'httpd', 'context', 'restorecon', 'fault-injection']
        self.exam_tips = [
            "restorecon -Rv /path is the fastest fix when contexts are wrong",
            "chcon is temporary — restorecon or semanage fcontext for persistence",
            "ausearch -m AVC -ts recent | audit2why is your first diagnostic command",
        ]

    def generate(self, **params):
        self.description = (
            "TROUBLESHOOTING: Apache Serving 403 Forbidden\n"
            + "=" * 50 + "\n\n"
            "Symptom: httpd is running but returns 403 Forbidden for all requests.\n"
            "The web content exists in /var/www/html but cannot be served.\n\n"
            "Tasks:\n"
            "  1. Diagnose why httpd cannot read the web content\n"
            "  2. Fix the root cause\n"
            "  3. Verify: curl http://localhost returns the page content\n"
            "  4. Ensure the fix is permanent (survives relabeling)"
        )
        self.hints = [
            "Check SELinux denials: ausearch -m AVC -ts recent | audit2why",
            "Inspect the context with ls -lZ and compare to a working web root",
            "Web content is normally labelled with the httpd_sys_content_t type",
            "Restore the default file context recursively so it survives a relabel",
        ]
        return self

    def inject_fault(self):
        # Create a test file so there's actually content to serve
        os.makedirs(self.web_root, exist_ok=True)
        test_file = f'{self.web_root}/index.html'
        if not os.path.exists(test_file):
            with open(test_file, 'w') as f:
                f.write('<html><body>RHCSA test</body></html>\n')

        # Set wrong SELinux type — etc_t blocks httpd from reading
        r = _run(['chcon', '-R', '-t', 'etc_t', self.web_root])
        if r.returncode != 0:
            return False, f"chcon failed: {r.stderr.strip()}"

        save_fault_state(self.id, {'path': self.web_root})

        if _httpd_present():
            # Real symptom: run httpd and hit it so a genuine AVC denial lands
            # in the audit log for the candidate to find.
            _ensure_httpd_running(self.id)
            _run(['curl', '-s', '-o', '/dev/null', '--max-time', '3',
                  'http://localhost'], timeout=8)
        else:
            # httpd isn't installed (user declined the install offer) — leave
            # the evidence a real denial would have produced so the documented
            # diagnosis path (ausearch/audit2why, journal) still works.
            _seed_avc_denial(
                '{ read } for  pid=2841 comm="httpd" name="index.html" '
                f'dev="dm-0" ino=17825828 '
                'scontext=system_u:system_r:httpd_t:s0 '
                'tcontext=unconfined_u:object_r:etc_t:s0 tclass=file permissive=0',
                'SELinux is preventing /usr/sbin/httpd from read access on the '
                f'file {self.web_root}/index.html. For complete SELinux messages '
                'run: ausearch -m AVC | audit2why')

        return True, f"Set wrong SELinux context (etc_t) on {self.web_root}"

    def restore_fault(self):
        msgs = []
        _restore_selinux_context({'path': self.web_root}, msgs)
        _restore_httpd_setup(self.id, msgs)
        clear_fault_state()
        return True, '; '.join(msgs)

    def validate(self):
        checks = []
        score = 0

        # Check 1: context is correct (6 pts)
        r = execute_safe(['ls', '-Zd', self.web_root])
        if r.success and 'httpd_sys_content_t' in r.stdout:
            checks.append(ValidationCheck("selinux_context", True, 6, message=f"{self.web_root} has correct SELinux type"))
            score += 6
        else:
            ctx = r.stdout.strip() if r.success else 'unknown'
            checks.append(ValidationCheck("selinux_context", False, 0, max_points=6,
                                          message=f"Wrong SELinux context: {ctx}"))

        # Check 2: restorecon would be a no-op (policy matches reality) (4 pts)
        r = execute_safe(['restorecon', '-Rvn', self.web_root])
        if r.success and not r.stdout.strip():
            checks.append(ValidationCheck("context_persistent", True, 4, message="Context matches policy (persistent)"))
            score += 4
        else:
            checks.append(ValidationCheck("context_persistent", False, 0, max_points=4,
                                          message="Context doesn't match policy — won't survive relabel"))

        # Check 3: httpd running (2 pts)
        r = execute_safe(['systemctl', 'is-active', 'httpd'])
        if r.success and 'active' in r.stdout:
            checks.append(ValidationCheck("httpd_running", True, 2, message="httpd is running"))
            score += 2
        else:
            checks.append(ValidationCheck("httpd_running", False, 0, max_points=2, message="httpd is not running"))

        # Check 4: curl returns 200 (2 pts)
        r = execute_safe(['curl', '-s', '-o', '/dev/null', '-w', '%{http_code}', 'http://localhost'])
        if r.success and r.stdout.strip() == '200':
            checks.append(ValidationCheck("httpd_serving", True, 2, message="httpd returning HTTP 200"))
            score += 2
        else:
            checks.append(ValidationCheck("httpd_serving", False, 0, max_points=2,
                                          message=f"httpd not serving correctly (got {r.stdout.strip()})"))

        return ValidationResult(self.id, score >= self.points * 0.7, score, self.points, checks)


# ── SELinux: boolean off for httpd network connect ────────────────────────────

@TaskRegistry.register("troubleshooting")
class SELinuxHttpdBooleanFaultTask(TroubleshootingTask):

    required_packages = ['httpd']

    def __init__(self):
        super().__init__(
            id="fault_selinux_boolean_httpd_001",
            category="troubleshooting",
            difficulty="exam",
            points=12
        )
        self.boolean_name = 'httpd_can_network_connect'
        self.exam_domain = 7
        self.tags = ['selinux', 'boolean', 'httpd', 'fault-injection', 'exam-seen']
        self.exam_tips = [
            "getsebool -a | grep httpd lists all httpd-related booleans",
            "Always use -P flag with setsebool to make changes persistent",
            "audit2why tells you WHICH boolean to enable from an AVC denial",
        ]
        self._original_value = 'on'

    def generate(self, **params):
        self.description = (
            "TROUBLESHOOTING: Apache Cannot Connect to Backend\n"
            + "=" * 50 + "\n\n"
            "Symptom: httpd is running but cannot make outgoing network connections\n"
            "to a backend service (proxy, database, API). Requests time out.\n\n"
            "Tasks:\n"
            "  1. Identify the SELinux denial using audit logs\n"
            "  2. Determine the correct boolean to enable\n"
            "  3. Enable the boolean persistently across reboots"
        )
        self.hints = [
            "Check denials: ausearch -m AVC -ts recent | audit2why",
            "List relevant booleans: getsebool -a | grep httpd",
            "audit2why names the boolean to enable — set it persistently (-P)",
            "Verify with getsebool once you have enabled it",
        ]
        return self

    def inject_fault(self):
        # Save current value first
        r = _run(['getsebool', self.boolean_name])
        if r.returncode == 0 and '->' in r.stdout:
            val = r.stdout.split('->')[-1].strip().split()[0]
            self._original_value = val

        r = _run(['setsebool', '-P', self.boolean_name, 'off'])
        if r.returncode != 0:
            return False, f"setsebool failed: {r.stderr.strip()}"

        save_fault_state(self.id, {
            'boolean': self.boolean_name,
            'original_value': self._original_value,
        })

        if _httpd_present():
            _ensure_httpd_running(self.id)

        # Curling localhost:8080 as a client (the old approach here) never
        # makes httpd itself originate the outbound connection, so it can't
        # produce a genuine name_connect denial — nothing else in this fault
        # causes httpd to actually dial out. Seed the AVC evidence a real
        # denial would have left so ausearch/audit2why still find it.
        _seed_avc_denial(
            '{ name_connect } for  pid=2841 comm="httpd" dest=8080 '
            'scontext=system_u:system_r:httpd_t:s0 '
            'tcontext=system_u:object_r:http_cache_port_t:s0 '
            'tclass=tcp_socket permissive=0',
            'SELinux is preventing /usr/sbin/httpd from name_connect access '
            'on the tcp_socket port 8080. For complete SELinux messages '
            'run: ausearch -m AVC | audit2why')

        return True, f"Set {self.boolean_name}=off (was {self._original_value})"

    def restore_fault(self):
        msgs = []
        _restore_selinux_boolean({'boolean': self.boolean_name, 'original_value': self._original_value}, msgs)
        _restore_httpd_setup(self.id, msgs)
        clear_fault_state()
        return True, '; '.join(msgs)

    def validate(self):
        checks = []
        score = 0

        # Check 1: boolean is on (7 pts)
        r = execute_safe(['getsebool', self.boolean_name])
        if r.success and '-> on' in r.stdout:
            checks.append(ValidationCheck("boolean_enabled", True, 7,
                                          message=f"{self.boolean_name} is on"))
            score += 7
        else:
            val = r.stdout.strip() if r.success else 'unknown'
            checks.append(ValidationCheck("boolean_enabled", False, 0, max_points=7,
                                          message=f"{self.boolean_name} is off or unknown: {val}"))

        # Check 2: persistent (survives reboot) — check the permanent store (5 pts)
        r = execute_safe(['semanage', 'boolean', '-l'])
        if r.success:
            for line in r.stdout.splitlines():
                if self.boolean_name in line and '(on' in line:
                    checks.append(ValidationCheck("boolean_persistent", True, 5,
                                                  message="Boolean change is persistent"))
                    score += 5
                    break
            else:
                checks.append(ValidationCheck("boolean_persistent", False, 0, max_points=5,
                                              message="Boolean is on now but NOT set persistently (-P flag required)"))
        else:
            checks.append(ValidationCheck("boolean_persistent", False, 0, max_points=5,
                                          message="Could not verify persistence (semanage not available)"))

        return ValidationResult(self.id, score >= self.points * 0.7, score, self.points, checks)


# ── Firewall: http port blocked ───────────────────────────────────────────────

@TaskRegistry.register("troubleshooting")
class FirewallHttpBlockedFaultTask(TroubleshootingTask):

    required_packages = ['httpd']

    def __init__(self):
        super().__init__(
            id="fault_firewall_http_001",
            category="troubleshooting",
            difficulty="exam",
            points=10
        )
        self.zone = 'public'
        self.service = 'http'
        self.exam_domain = 7
        self.tags = ['firewalld', 'http', 'fault-injection']
        self.exam_tips = [
            "Always add --permanent AND reload, or use both flags together",
            "firewall-cmd --list-all shows everything currently active in a zone",
            "Without --permanent, the rule disappears after next reload or reboot",
        ]

    def generate(self, **params):
        self.description = (
            "TROUBLESHOOTING: Web Server Unreachable from Network\n"
            + "=" * 50 + "\n\n"
            "Symptom: httpd is running and serving locally (curl localhost works),\n"
            "but the web server is not reachable from external clients on port 80.\n\n"
            "Tasks:\n"
            "  1. Identify why external HTTP traffic is blocked\n"
            "  2. Open port 80 / the http service in the firewall\n"
            "  3. Make the rule permanent so it survives reboots"
        )
        self.hints = [
            "Check active rules: firewall-cmd --list-all",
            "Add the http service to the active zone and make the change permanent",
            "Reload to activate permanent changes: firewall-cmd --reload",
            "Verify: firewall-cmd --query-service=http",
        ]
        return self

    def inject_fault(self):
        if not _httpd_present():
            return False, "httpd is not installed (declined at the install offer) — skipping this scenario"

        # Content + a running httpd so "curl localhost works" is actually true
        os.makedirs('/var/www/html', exist_ok=True)
        test_file = '/var/www/html/index.html'
        if not os.path.exists(test_file):
            with open(test_file, 'w') as f:
                f.write('<html><body>RHCSA test</body></html>\n')
        _ensure_httpd_running(self.id)

        # Only remove if currently present (avoid injecting into already-broken state)
        r = _run(['firewall-cmd', '--zone=public', '--query-service=http'])
        was_present = r.returncode == 0

        _run(['firewall-cmd', '--zone=public', '--remove-service=http'])
        _run(['firewall-cmd', '--zone=public', '--remove-service=http', '--permanent'])

        save_fault_state(self.id, {
            'zone': self.zone,
            'service': self.service,
            'was_present': was_present,
        })
        return True, "Removed http service from public zone (runtime + permanent)"

    def restore_fault(self):
        msgs = []
        _restore_firewall({'zone': self.zone, 'service': self.service}, msgs)
        _restore_httpd_setup(self.id, msgs)
        clear_fault_state()
        return True, '; '.join(msgs)

    def validate(self):
        checks = []
        score = 0

        # Check 1: service active in runtime (4 pts)
        r = execute_safe(['firewall-cmd', '--zone=public', '--query-service=http'])
        if r.success and r.stdout.strip() == 'yes':
            checks.append(ValidationCheck("fw_runtime", True, 4, message="http service active in runtime firewall"))
            score += 4
        else:
            checks.append(ValidationCheck("fw_runtime", False, 0, max_points=4,
                                          message="http service not in runtime firewall rules"))

        # Check 2: service permanent (4 pts)
        r = execute_safe(['firewall-cmd', '--zone=public', '--query-service=http', '--permanent'])
        if r.success and r.stdout.strip() == 'yes':
            checks.append(ValidationCheck("fw_permanent", True, 4, message="http service in permanent config"))
            score += 4
        else:
            checks.append(ValidationCheck("fw_permanent", False, 0, max_points=4,
                                          message="http service NOT in permanent config — won't survive reboot"))

        # Check 3: httpd listening (2 pts)
        r = execute_safe(['ss', '-tlnp'])
        if r.success and (':80 ' in r.stdout or ':80\n' in r.stdout):
            checks.append(ValidationCheck("httpd_listening", True, 2, message="httpd listening on port 80"))
            score += 2
        else:
            checks.append(ValidationCheck("httpd_listening", False, 0, max_points=2,
                                          message="httpd not listening on port 80"))

        return ValidationResult(self.id, score >= self.points * 0.7, score, self.points, checks)


# ── SSHD: bad config line preventing restart ──────────────────────────────────

@TaskRegistry.register("troubleshooting")
class SshdBadConfigFaultTask(TroubleshootingTask):
    MARKER = '# RHCSA-FAULT-INJECT'

    def __init__(self):
        super().__init__(
            id="fault_sshd_config_001",
            category="troubleshooting",
            difficulty="exam",
            points=10
        )
        self.exam_domain = 7
        self.tags = ['ssh', 'sshd_config', 'fault-injection']
        self.exam_tips = [
            "sshd -t validates config without restarting — always run this first",
            "journalctl -xeu sshd shows the exact line that failed to parse",
            "Never restart sshd without validating config — you'll lock yourself out",
        ]

    def generate(self, **params):
        self.description = (
            "TROUBLESHOOTING: sshd Will Not Restart\n"
            + "=" * 50 + "\n\n"
            "Symptom: Attempting to restart sshd fails with a config parse error.\n"
            "Current sessions still work, but sshd cannot be reloaded or restarted.\n\n"
            "Tasks:\n"
            "  1. Identify the bad configuration line\n"
            "  2. Remove or fix the offending entry in /etc/ssh/sshd_config\n"
            "  3. Verify the config is valid with sshd -t\n"
            "  4. Successfully restart sshd"
        )
        self.hints = [
            "Test config without restarting: sshd -t",
            "Check what failed: journalctl -xeu sshd --no-pager | tail -20",
            "Look for unusual lines in /etc/ssh/sshd_config",
            "After fixing, restart: systemctl restart sshd",
        ]
        return self

    def inject_fault(self):
        bad_line = f'InvalidDirective ExamBreaker {self.MARKER}\n'
        with open('/etc/ssh/sshd_config', 'a') as f:
            f.write(bad_line)

        save_fault_state(self.id, {'marker': self.MARKER})
        return True, f"Appended invalid directive to /etc/ssh/sshd_config"

    def restore_fault(self):
        msgs = []
        _restore_sshd_config({'marker': self.MARKER}, msgs)
        clear_fault_state()
        return True, '; '.join(msgs)

    def validate(self):
        checks = []
        score = 0

        # Check 1: config parses cleanly (5 pts)
        r = execute_safe(['sshd', '-t'])
        if r.success:
            checks.append(ValidationCheck("sshd_config_valid", True, 5, message="sshd config validates without errors"))
            score += 5
        else:
            checks.append(ValidationCheck("sshd_config_valid", False, 0, max_points=5,
                                          message=f"sshd -t still fails: {r.stderr.strip()[:100]}"))

        # Check 2: bad line removed (3 pts)
        # grep -c exits 1 (non-success) when the count is 0, so success can't be required here
        r = execute_safe(['grep', '-c', 'InvalidDirective', '/etc/ssh/sshd_config'])
        if r.stdout.strip() == '0':
            checks.append(ValidationCheck("bad_line_removed", True, 3, message="Invalid directive removed from sshd_config"))
            score += 3
        else:
            checks.append(ValidationCheck("bad_line_removed", False, 0, max_points=3,
                                          message="InvalidDirective line still present in sshd_config"))

        # Check 3: sshd running (2 pts)
        r = execute_safe(['systemctl', 'is-active', 'sshd'])
        if r.success and 'active' in r.stdout:
            checks.append(ValidationCheck("sshd_running", True, 2, message="sshd is running"))
            score += 2
        else:
            checks.append(ValidationCheck("sshd_running", False, 0, max_points=2, message="sshd is not running"))

        return ValidationResult(self.id, score >= self.points * 0.7, score, self.points, checks)


# ── Service: httpd stopped and disabled ──────────────────────────────────────

@TaskRegistry.register("troubleshooting")
class HttpdDisabledFaultTask(TroubleshootingTask):

    required_packages = ['httpd']

    def __init__(self):
        super().__init__(
            id="fault_service_httpd_001",
            category="troubleshooting",
            difficulty="exam",
            points=8
        )
        self.service = 'httpd'
        self.exam_domain = 4
        self.tags = ['services', 'httpd', 'systemd', 'fault-injection']
        self.exam_tips = [
            "systemctl enable --now does both start and enable in one command",
            "Always check 'systemctl status' first — it often says exactly why it failed",
        ]
        self._was_active = False
        self._was_enabled = False

    def generate(self, **params):
        self.description = (
            "TROUBLESHOOTING: Web Service Not Running at Boot\n"
            + "=" * 50 + "\n\n"
            "Symptom: After a reboot, httpd is not running. The service was\n"
            "previously configured but is now stopped and disabled.\n\n"
            "Tasks:\n"
            "  1. Start the httpd service\n"
            "  2. Enable it to start automatically at boot\n"
            "  3. Verify both states"
        )
        self.hints = [
            "Check service state: systemctl status httpd",
            "Start the service now AND enable it so it comes back at boot",
            "Verify: systemctl is-active httpd && systemctl is-enabled httpd",
        ]
        return self

    def inject_fault(self):
        if not _httpd_present():
            return False, "httpd is not installed (declined at the install offer) — skipping this scenario"

        r = _run(['systemctl', 'is-active', self.service])
        self._was_active = r.returncode == 0
        r = _run(['systemctl', 'is-enabled', self.service])
        self._was_enabled = 'enabled' in r.stdout

        _run(['systemctl', 'stop', self.service])
        _run(['systemctl', 'disable', self.service])

        save_fault_state(self.id, {
            'service': self.service,
            'was_active': self._was_active,
            'was_enabled': self._was_enabled,
        })
        return True, f"Stopped and disabled {self.service}"

    def restore_fault(self):
        msgs = []
        _restore_service({
            'service': self.service,
            'was_active': self._was_active,
            'was_enabled': self._was_enabled,
        }, msgs)
        _restore_httpd_setup(self.id, msgs)
        clear_fault_state()
        return True, '; '.join(msgs)

    def validate(self):
        checks = []
        score = 0

        r = execute_safe(['systemctl', 'is-active', self.service])
        if r.success and 'active' in r.stdout:
            checks.append(ValidationCheck("service_active", True, 4, message=f"{self.service} is running"))
            score += 4
        else:
            checks.append(ValidationCheck("service_active", False, 0, max_points=4,
                                          message=f"{self.service} is not running"))

        r = execute_safe(['systemctl', 'is-enabled', self.service])
        if r.success and 'enabled' in r.stdout:
            checks.append(ValidationCheck("service_enabled", True, 4, message=f"{self.service} enabled at boot"))
            score += 4
        else:
            checks.append(ValidationCheck("service_enabled", False, 0, max_points=4,
                                          message=f"{self.service} NOT enabled at boot"))

        return ValidationResult(self.id, score >= self.points * 0.7, score, self.points, checks)


# ── Sudoers: file has wrong permissions ──────────────────────────────────────

@TaskRegistry.register("troubleshooting")
class SudoersWrongPermsFaultTask(TroubleshootingTask):
    PRACTICE_USER = 'sudopractice'
    SUDOERS_FILE = '/etc/sudoers.d/sudopractice'

    def __init__(self):
        super().__init__(
            id="fault_sudoers_perms_001",
            category="troubleshooting",
            difficulty="exam",
            points=10
        )
        self.exam_domain = 3
        self.tags = ['sudo', 'sudoers', 'permissions', 'fault-injection']
        self.exam_tips = [
            "sudo ignores any sudoers.d file with permissions other than 0440",
            "Always use visudo -c to validate before relying on a sudoers file",
            "chmod 440 /etc/sudoers.d/file — not 0777, not 0600",
        ]

    def generate(self, **params):
        self.description = (
            f"TROUBLESHOOTING: sudo Privileges Not Working\n"
            + "=" * 50 + "\n\n"
            f"Symptom: User '{self.PRACTICE_USER}' has a sudoers file in\n"
            f"/etc/sudoers.d/ but sudo still says they are not in the sudoers file.\n\n"
            "Tasks:\n"
            f"  1. Identify why sudo is ignoring /etc/sudoers.d/{self.PRACTICE_USER}\n"
            "  2. Fix the issue\n"
            "  3. Verify sudo -l shows the user's privileges"
        )
        self.hints = [
            "Check file permissions: ls -l /etc/sudoers.d/",
            "sudo ignores files with world-writable or group-writable permissions",
            "Restore the restrictive permissions sudo requires on a sudoers file",
            f"Verify: sudo -l -U {self.PRACTICE_USER}",
        ]
        return self

    def inject_fault(self):
        # Create user if missing
        r = _run(['id', self.PRACTICE_USER])
        if r.returncode != 0:
            _run(['useradd', '-M', '-s', '/sbin/nologin', self.PRACTICE_USER])

        # Write sudoers file with correct content but wrong permissions
        content = f"{self.PRACTICE_USER} ALL=(ALL) NOPASSWD: /usr/bin/systemctl status\n"
        with open(self.SUDOERS_FILE, 'w') as f:
            f.write(content)
        os.chmod(self.SUDOERS_FILE, 0o777)   # sudo will ignore this

        save_fault_state(self.id, {
            'path': self.SUDOERS_FILE,
            'user': self.PRACTICE_USER,
            'original_perms': '0440',
        })
        return True, f"Created {self.SUDOERS_FILE} with permissions 0777 (sudo will ignore)"

    def restore_fault(self):
        msgs = []
        if os.path.exists(self.SUDOERS_FILE):
            os.remove(self.SUDOERS_FILE)
            msgs.append(f"Removed {self.SUDOERS_FILE}")
        # Remove practice user
        _run(['userdel', self.PRACTICE_USER])
        msgs.append(f"Removed practice user {self.PRACTICE_USER}")
        clear_fault_state()
        return True, '; '.join(msgs)

    def validate(self):
        checks = []
        score = 0

        # Check 1: file exists (2 pts)
        if os.path.exists(self.SUDOERS_FILE):
            checks.append(ValidationCheck("file_exists", True, 2, message=f"{self.SUDOERS_FILE} exists"))
            score += 2
        else:
            checks.append(ValidationCheck("file_exists", False, 0, max_points=2,
                                          message=f"{self.SUDOERS_FILE} was deleted"))
            return ValidationResult(self.id, False, score, self.points, checks)

        # Check 2: permissions are 0440 (4 pts)
        stat = os.stat(self.SUDOERS_FILE)
        perms = oct(stat.st_mode)[-4:]
        if perms in ('0440', '0400'):
            checks.append(ValidationCheck("correct_perms", True, 4, message=f"Permissions are {perms}"))
            score += 4
        else:
            checks.append(ValidationCheck("correct_perms", False, 0, max_points=4,
                                          message=f"Permissions are {perms}, need 0440"))

        # Check 3: sudo -l recognizes the user (4 pts)
        r = execute_safe(['sudo', '-l', '-U', self.PRACTICE_USER])
        if r.success and 'systemctl' in r.stdout:
            checks.append(ValidationCheck("sudo_works", True, 4, message=f"sudo -l shows privileges for {self.PRACTICE_USER}"))
            score += 4
        else:
            checks.append(ValidationCheck("sudo_works", False, 0, max_points=4,
                                          message=f"sudo still not recognizing {self.PRACTICE_USER}"))

        return ValidationResult(self.id, score >= self.points * 0.7, score, self.points, checks)


# ── Filesystem: bad fstab entry ───────────────────────────────────────────────

@TaskRegistry.register("troubleshooting")
class BadFstabFaultTask(TroubleshootingTask):
    MARKER = '# RHCSA-FAULT-FSTAB'
    MOUNTPOINT = '/mnt/faulttest'

    def __init__(self):
        super().__init__(
            id="fault_fstab_001",
            category="troubleshooting",
            difficulty="exam",
            points=10
        )
        self.exam_domain = 4
        self.tags = ['fstab', 'mount', 'filesystem', 'fault-injection']
        self.exam_tips = [
            "mount -a tests all fstab entries — run it before rebooting",
            "findmnt --verify --fstab catches syntax errors without mounting",
            "A bad fstab entry will drop you into emergency mode on next boot",
        ]

    def generate(self, **params):
        self.description = (
            "TROUBLESHOOTING: Bad /etc/fstab Entry\n"
            + "=" * 50 + "\n\n"
            "Symptom: After adding a filesystem to /etc/fstab, running 'mount -a'\n"
            "produces errors. The bad entry will cause an emergency mode boot.\n\n"
            "Tasks:\n"
            "  1. Identify the bad entry in /etc/fstab\n"
            "  2. Fix or remove the problematic line\n"
            "  3. Verify 'mount -a' runs without errors"
        )
        self.hints = [
            "Test fstab: mount -a",
            "Validate syntax: findmnt --verify --fstab",
            "Inspect entries: cat /etc/fstab",
            "A non-existent UUID or wrong device path causes the error",
            f"Look for the entry referencing {self.MOUNTPOINT}",
        ]
        return self

    def inject_fault(self):
        os.makedirs(self.MOUNTPOINT, exist_ok=True)
        bad_entry = (
            f"UUID=00000000-dead-beef-0000-000000000000 {self.MOUNTPOINT} "
            f"xfs defaults 0 0 {self.MARKER}\n"
        )
        with open('/etc/fstab', 'a') as f:
            f.write(bad_entry)

        save_fault_state(self.id, {'marker': self.MARKER})
        return True, f"Added non-existent UUID entry for {self.MOUNTPOINT} to /etc/fstab"

    def restore_fault(self):
        msgs = []
        _restore_fstab({'marker': self.MARKER}, msgs)
        try:
            os.rmdir(self.MOUNTPOINT)
        except OSError:
            pass
        clear_fault_state()
        return True, '; '.join(msgs)

    def validate(self):
        checks = []
        score = 0

        # Check 1: bad line gone (5 pts)
        # grep -c exits 1 (non-success) when the count is 0, so success can't be required here
        r = execute_safe(['grep', '-c', 'RHCSA-FAULT-FSTAB', '/etc/fstab'])
        if r.stdout.strip() == '0':
            checks.append(ValidationCheck("bad_entry_removed", True, 5, message="Bad fstab entry removed"))
            score += 5
        else:
            checks.append(ValidationCheck("bad_entry_removed", False, 0, max_points=5,
                                          message="Bad fstab entry still present"))

        # Check 2: mount -a succeeds (5 pts)
        r = execute_safe(['mount', '-a'])
        if r.returncode == 0:
            checks.append(ValidationCheck("mount_a_clean", True, 5, message="mount -a completes without errors"))
            score += 5
        else:
            checks.append(ValidationCheck("mount_a_clean", False, 0, max_points=5,
                                          message=f"mount -a still fails: {r.stderr.strip()[:100]}"))

        return ValidationResult(self.id, score >= self.points * 0.7, score, self.points, checks)


# ── Legacy descriptive tasks (kept, no fault injection) ──────────────────────

class SSHNotStartingTask(TroubleshootingTask):
    """Kept for compatibility — descriptive only, no fault injection."""
    has_fault_injection = False

    def __init__(self):
        super().__init__(
            id="troubleshoot_ssh_001",
            category="troubleshooting",
            difficulty="exam",
            points=12
        )

    def generate(self, **params):
        self.description = (
            "TROUBLESHOOTING: SSH Service Won't Start\n"
            "Symptom: sshd fails to start with 'Permission denied' binding to port.\n\n"
            "Your task:\n"
            "  1. Diagnose the root cause\n"
            "  2. Fix the problem\n"
            "  3. Ensure SSH service starts and is enabled at boot"
        )
        self.hints = [
            "Start by checking: systemctl status sshd",
            "Look at journal logs: journalctl -xeu sshd",
            "Check SELinux denials: ausearch -m AVC -ts recent",
        ]
        return self

    def inject_fault(self):
        return False, "Legacy task — no fault injection"

    def restore_fault(self):
        return True, "Nothing to restore"

    def validate(self):
        from validators.command_validators import validate_service_state, validate_service_enabled
        checks = []
        score = 0
        if validate_service_state('sshd', 'active'):
            checks.append(ValidationCheck("sshd_running", True, 6, message="SSHD is running"))
            score += 6
        else:
            checks.append(ValidationCheck("sshd_running", False, 0, max_points=6, message="SSHD not running"))
        if validate_service_enabled('sshd', True):
            checks.append(ValidationCheck("sshd_enabled", True, 6, message="SSHD enabled at boot"))
            score += 6
        else:
            checks.append(ValidationCheck("sshd_enabled", False, 0, max_points=6, message="SSHD not enabled"))
        return ValidationResult(self.id, score >= self.points * 0.7, score, self.points, checks)
