"""
Time services tasks for RHCSA exam (chrony, timedatectl).
"""

import random
import logging
from tasks.base import BaseTask
from tasks.registry import TaskRegistry
from core.validator import ValidationCheck, ValidationResult
from validators.safe_executor import execute_safe
from validators.file_validators import validate_file_exists, validate_file_contains


logger = logging.getLogger(__name__)


# ── Fault injection for time-sync tasks ──────────────────────────────────────
# On a fresh RHEL system chronyd is already active+enabled and NTP is already
# on, so a "make NTP work" task would otherwise pass without the candidate doing
# anything. These helpers break that default state so real work is required.

def _snapshot_chrony_conf():
    """Return the current /etc/chrony.conf content, or None if unreadable.
    Stored in the fault state so teardown puts the file back exactly as it
    was before the candidate edited it."""
    try:
        with open('/etc/chrony.conf') as f:
            return f.read()
    except OSError:
        return None


def _inject_time_sync_fault(task_id):
    """Stop/disable chronyd and turn NTP off, saving prior state for restore."""
    from tasks.troubleshooting import save_fault_state, _run

    act = _run(['systemctl', 'is-active', 'chronyd'])
    was_active = act.stdout.strip() == 'active'
    en = _run(['systemctl', 'is-enabled', 'chronyd'])
    was_enabled = 'enabled' in (en.stdout or '')
    ntp = _run(['timedatectl', 'show', '--property=NTP'])
    ntp_was_on = 'yes' in (ntp.stdout or '').lower()

    _run(['timedatectl', 'set-ntp', 'false'])
    _run(['systemctl', 'stop', 'chronyd'])
    _run(['systemctl', 'disable', 'chronyd'])

    info = {
        'chronyd_was_active': was_active,
        'chronyd_was_enabled': was_enabled,
        'ntp_was_on': ntp_was_on,
        'chrony_conf': _snapshot_chrony_conf(),
    }
    save_fault_state(task_id, info)
    return info, "Stopped/disabled chronyd and turned NTP off"


def _restore_time_sync_fault(info):
    """Restore chronyd/NTP to the state captured by _inject_time_sync_fault."""
    from tasks.troubleshooting import _restore_time_sync, clear_fault_state
    msgs = []
    _restore_time_sync(info or {}, msgs)
    clear_fault_state()
    return '; '.join(msgs)


@TaskRegistry.register("time_services")
class ConfigureTimezoneTask(BaseTask):
    """Set system timezone."""

    def __init__(self):
        super().__init__(
            id="time_tz_001",
            category="time_services",
            difficulty="easy",
            points=6
        )
        self.timezone = None

    def generate(self, **params):
        """Generate timezone task."""
        timezones = [
            'America/New_York',
            'America/Los_Angeles',
            'Europe/London',
            'Asia/Tokyo',
            'UTC'
        ]
        self.timezone = params.get('timezone', random.choice(timezones))

        self.description = (
            f"Configure system timezone:\n"
            f"  - Set timezone to: {self.timezone}\n"
            f"  - Change must be persistent"
        )

        self.hints = [
            "List timezones: timedatectl list-timezones",
            f"Set timezone: timedatectl set-timezone {self.timezone}",
            "Verify: timedatectl",
            "Alternative: ln -sf /usr/share/zoneinfo/{tz} /etc/localtime"
        ]

        return self

    def validate(self):
        """Validate timezone configuration."""
        checks = []
        total_points = 0

        result = execute_safe(['timedatectl', 'show', '--property=Timezone'])
        if result.success:
            current_tz = result.stdout.strip().replace('Timezone=', '')
            if current_tz == self.timezone:
                checks.append(ValidationCheck(
                    name="timezone_set",
                    passed=True,
                    points=6,
                    message=f"Timezone is {self.timezone}"
                ))
                total_points += 6
            else:
                checks.append(ValidationCheck(
                    name="timezone_set",
                    passed=False,
                    points=0,
                    max_points=6,
                    message=f"Timezone is {current_tz}, expected {self.timezone}"
                ))
        else:
            checks.append(ValidationCheck(
                name="timezone_set",
                passed=False,
                points=0,
                max_points=6,
                message="Could not check timezone"
            ))

        passed = total_points >= (self.points * 0.7)
        return ValidationResult(self.id, passed, total_points, self.points, checks)


@TaskRegistry.register("time_services")
class ConfigureChronydTask(BaseTask):
    """Configure chrony for NTP synchronization."""

    def __init__(self):
        super().__init__(
            id="time_chrony_001",
            category="time_services",
            difficulty="medium",
            points=12
        )
        self.has_fault_injection = True
        self._fault_info = None
        self.ntp_server = None

    def generate(self, **params):
        """Generate chrony configuration task."""
        # Real, reachable NTP sources only — an example.com/.org placeholder
        # here can never actually sync (see issue #92), and check 4 below
        # validates real synchronization against whatever server is
        # configured.
        ntp_servers = [
            '0.rhel.pool.ntp.org',
            '1.rhel.pool.ntp.org',
            '2.rhel.pool.ntp.org',
            'time.cloudflare.com',
        ]
        self.ntp_server = params.get('server', random.choice(ntp_servers))

        self.description = (
            f"Configure chrony NTP synchronization:\n"
            f"  - NTP Server: {self.ntp_server}\n"
            f"  - Edit /etc/chrony.conf\n"
            f"  - Enable and start chronyd service\n"
            f"  - Verify synchronization"
        )

        self.hints = [
            f"Add to /etc/chrony.conf: server {self.ntp_server} iburst",
            f"Or: pool {self.ntp_server} iburst",
            "Restart service: systemctl restart chronyd",
            "Enable service: systemctl enable chronyd",
            "Check sync: chronyc sources",
            "Check tracking: chronyc tracking"
        ]

        return self

    def inject_fault(self):
        self._fault_info, msg = _inject_time_sync_fault(self.id)
        return True, msg

    def restore_fault(self):
        return True, _restore_time_sync_fault(self._fault_info)

    def validate(self):
        """Validate chrony configuration."""
        checks = []
        total_points = 0

        # Check 1: chronyd is running (4 points)
        result = execute_safe(['systemctl', 'is-active', 'chronyd'])
        if result.success and result.stdout.strip() == 'active':
            checks.append(ValidationCheck(
                name="chronyd_running",
                passed=True,
                points=4,
                message="chronyd service is running"
            ))
            total_points += 4
        else:
            checks.append(ValidationCheck(
                name="chronyd_running",
                passed=False,
                points=0,
                max_points=4,
                message="chronyd service is not running"
            ))

        # Check 2: chronyd is enabled (2 points)
        result = execute_safe(['systemctl', 'is-enabled', 'chronyd'])
        if result.success and 'enabled' in result.stdout:
            checks.append(ValidationCheck(
                name="chronyd_enabled",
                passed=True,
                points=2,
                message="chronyd service is enabled"
            ))
            total_points += 2
        else:
            checks.append(ValidationCheck(
                name="chronyd_enabled",
                passed=False,
                points=0,
                max_points=2,
                message="chronyd service is not enabled"
            ))

        # Check 3: NTP server in config (4 points)
        if validate_file_contains('/etc/chrony.conf', self.ntp_server):
            checks.append(ValidationCheck(
                name="ntp_configured",
                passed=True,
                points=4,
                message=f"NTP server {self.ntp_server} in config"
            ))
            total_points += 4
        elif validate_file_contains('/etc/chrony.conf', 'server ') or validate_file_contains('/etc/chrony.conf', 'pool '):
            checks.append(ValidationCheck(
                name="ntp_configured",
                passed=True,
                points=2,
                message="NTP servers configured (different server)"
            ))
            total_points += 2
        else:
            checks.append(ValidationCheck(
                name="ntp_configured",
                passed=False,
                points=0,
                max_points=4,
                message="No NTP server configured"
            ))

        # Check 4: NTP sync enabled (2 points)
        result = execute_safe(['timedatectl', 'show', '--property=NTPSynchronized'])
        if result.success and 'yes' in result.stdout.lower():
            checks.append(ValidationCheck(
                name="ntp_synced",
                passed=True,
                points=2,
                message="NTP is synchronized"
            ))
            total_points += 2
        else:
            checks.append(ValidationCheck(
                name="ntp_synced",
                passed=False,
                points=0,
                max_points=2,
                message="NTP not synchronized (may take time)"
            ))

        passed = total_points >= (self.points * 0.7)
        return ValidationResult(self.id, passed, total_points, self.points, checks)


@TaskRegistry.register("time_services")
class EnableNTPSyncTask(BaseTask):
    """Fault-injection: chronyd is stopped/disabled; user must re-enable it."""

    has_fault_injection = True

    def __init__(self):
        super().__init__(
            id="time_ntp_001",
            category="time_services",
            difficulty="easy",
            points=6
        )
        self.has_fault_injection = True
        self._fault_info = None
        self.exam_tips = [
            "'timedatectl set-ntp true' enables NTP and starts chronyd automatically.",
            "'systemctl enable --now chronyd' is the lower-level equivalent.",
            "Verify sync with: timedatectl status  (look for 'NTP service: active')",
        ]

    def generate(self, **params):
        self.description = (
            "TROUBLESHOOTING: NTP Time Sync Disabled\n"
            "Symptom: The system clock is not synchronizing with time servers.\n"
            "chronyd has been stopped and disabled.\n\n"
            "Tasks:\n"
            "  1. Re-enable automatic NTP time synchronization\n"
            "  2. Ensure the chronyd service is running\n"
            "  3. Verify NTP sync is active"
        )
        self.hints = [
            "Enable NTP: timedatectl set-ntp true",
            "Or: systemctl enable --now chronyd",
            "Verify: timedatectl  (look for 'NTP service: active')",
        ]
        return self

    def inject_fault(self):
        self._fault_info, msg = _inject_time_sync_fault(self.id)
        return True, msg

    def restore_fault(self):
        return True, _restore_time_sync_fault(self._fault_info)

    def validate(self):
        checks = []
        score = 0

        r = execute_safe(['timedatectl', 'show', '--property=NTP'])
        if r.success and 'NTP=yes' in r.stdout:
            checks.append(ValidationCheck("ntp_enabled", True, 3, message="NTP is enabled"))
            score += 3
        else:
            checks.append(ValidationCheck("ntp_enabled", False, 0, max_points=3,
                                          message="NTP is not enabled (timedatectl set-ntp true)"))

        r = execute_safe(['systemctl', 'is-active', 'chronyd'])
        svc_ok = r.success and r.stdout.strip() == 'active'
        if not svc_ok:
            r2 = execute_safe(['systemctl', 'is-active', 'ntpd'])
            svc_ok = r2.success and r2.stdout.strip() == 'active'
        if svc_ok:
            checks.append(ValidationCheck("service_running", True, 3, message="Time service is running"))
            score += 3
        else:
            checks.append(ValidationCheck("service_running", False, 0, max_points=3,
                                          message="No time service running (systemctl start chronyd)"))

        return ValidationResult(self.id, score >= self.points * 0.7, score, self.points, checks)


@TaskRegistry.register("time_services")
class SetSystemDateTask(BaseTask):
    """Set system date and time manually (requires disabling NTP first)."""

    has_fault_injection = True

    def __init__(self):
        super().__init__(
            id="time_set_001",
            category="time_services",
            difficulty="easy",
            points=6
        )
        self.target_time = None
        self.exam_tips = [
            "timedatectl set-ntp false MUST come before set-time or it will be rejected.",
            "After setting time manually, re-enable NTP: timedatectl set-ntp true",
            "The format is: timedatectl set-time 'YYYY-MM-DD HH:MM:SS'",
        ]

    def generate(self, **params):
        self.target_time = params.get('time', '2025-06-15 14:30:00')

        self.description = (
            f"Set the system clock manually:\n"
            f"  1. Disable NTP synchronization (required before manual set)\n"
            f"  2. Set the system time to: {self.target_time}\n"
            f"  3. Verify the time was applied\n"
            f"  (Re-enabling NTP afterwards is good practice but not validated here)"
        )
        self.hints = [
            "Disable NTP first: timedatectl set-ntp false",
            f"Set time: timedatectl set-time '{self.target_time}'",
            "Verify: timedatectl  or  date",
            "Re-enable after: timedatectl set-ntp true",
        ]
        return self

    def inject_fault(self):
        import subprocess as _sp
        import time
        # Start from NTP-enabled state so the user must disable it to set time.
        _sp.run(['timedatectl', 'set-ntp', 'true'], capture_output=True)
        _sp.run(['systemctl', 'enable', '--now', 'chronyd'], capture_output=True)
        from tasks.troubleshooting import save_fault_state
        # CLOCK_MONOTONIC is unaffected by the very clock changes this task asks
        # the candidate to make, so it's used at validate() time to measure how
        # much real time has passed since the clock was set, and at teardown —
        # together with the wall clock captured now, while it is still correct —
        # to reconstruct the real time and reset the clock even with no network
        # NTP available (see _restore_time_sync).
        save_fault_state(self.id, {'service': 'chronyd',
                                   'injected_monotonic': time.monotonic(),
                                   'injected_wallclock': time.time()})
        return True, "NTP is active — disable it, then set the clock to the target time"

    def restore_fault(self):
        from tasks.troubleshooting import (load_fault_state, clear_fault_state,
                                           _restore_time_sync)
        state = load_fault_state(self.id) or {}
        msgs = []
        # Resets the clock to (captured wall clock + elapsed monotonic time),
        # then re-enables NTP sync so a reachable server fine-corrects it.
        _restore_time_sync(state.get('restore_info') or {}, msgs)
        clear_fault_state()
        return True, '; '.join(msgs) or "Re-enabled NTP sync"

    def validate(self):
        import datetime
        import time
        from tasks.troubleshooting import load_fault_state
        checks = []
        score = 0

        # Check 1: NTP disabled (prerequisite the user must do)
        r = execute_safe(['timedatectl', 'show', '--property=NTP'])
        if r.success and 'NTP=no' in r.stdout:
            checks.append(ValidationCheck("ntp_disabled", True, 2,
                message="NTP is disabled — manual time setting is possible"))
            score += 2
        else:
            checks.append(ValidationCheck("ntp_disabled", False, 0, max_points=2,
                message="NTP is still active: run 'timedatectl set-ntp false' first"))

        # Check 2: System time matches the target, adjusted for real time that
        # has legitimately passed since the candidate set it. Once NTP is off
        # and the clock is set, it free-runs forward in real time — a candidate
        # who sets it correctly and then keeps working on other exam tasks will
        # see current_ts drift ahead of target_ts through no fault of their own.
        # elapsed (measured via CLOCK_MONOTONIC, which the clock change itself
        # can't affect) bounds how much of that forward drift is legitimate.
        try:
            target_dt = datetime.datetime.strptime(self.target_time, '%Y-%m-%d %H:%M:%S')
            r2 = execute_safe(['date', '+%s'])
            if r2.success:
                current_ts = int(r2.stdout.strip())
                target_ts = int(target_dt.timestamp())
                delta = current_ts - target_ts
                tolerance = 300

                elapsed = 0
                fault_state = load_fault_state(self.id)
                if fault_state and isinstance(fault_state.get('restore_info'), dict):
                    injected_monotonic = fault_state['restore_info'].get('injected_monotonic')
                    if injected_monotonic is not None:
                        elapsed = max(0, time.monotonic() - injected_monotonic)

                if -tolerance <= delta <= elapsed + tolerance:
                    checks.append(ValidationCheck("time_set", True, 4,
                        message=f"System time matches target ({self.target_time})"))
                    score += 4
                else:
                    checks.append(ValidationCheck("time_set", False, 0, max_points=4,
                        message=f"System time is off by {delta}s — run: timedatectl set-time '{self.target_time}'"))
            else:
                checks.append(ValidationCheck("time_set", False, 0, max_points=4,
                    message="Could not read system time"))
        except Exception:
            checks.append(ValidationCheck("time_set", False, 0, max_points=4,
                message="Time validation error"))

        return ValidationResult(self.id, score >= self.points * 0.7, score, self.points, checks)


@TaskRegistry.register("time_services")
class ConfigureNTPPoolTask(BaseTask):
    """Configure multiple NTP servers/pools."""

    has_fault_injection = True

    def __init__(self):
        super().__init__(
            id="time_pool_001",
            category="time_services",
            difficulty="medium",
            points=10
        )
        self.ntp_pools = None
        self._fault_info = None

    def inject_fault(self):
        """Nothing to break — the candidate only adds pool lines. But snapshot
        chrony.conf and the service state so teardown can put both back."""
        from tasks.troubleshooting import save_fault_state, _run
        act = _run(['systemctl', 'is-active', 'chronyd'])
        en = _run(['systemctl', 'is-enabled', 'chronyd'])
        ntp = _run(['timedatectl', 'show', '--property=NTP'])
        self._fault_info = {
            'chronyd_was_active': act.stdout.strip() == 'active',
            'chronyd_was_enabled': 'enabled' in (en.stdout or ''),
            'ntp_was_on': 'yes' in (ntp.stdout or '').lower(),
            'chrony_conf': _snapshot_chrony_conf(),
        }
        save_fault_state(self.id, self._fault_info)
        return True, "Snapshotted time-sync configuration for session cleanup"

    def restore_fault(self):
        return True, _restore_time_sync_fault(self._fault_info)

    def generate(self, **params):
        """Generate NTP pool configuration task."""
        self.ntp_pools = params.get('pools', [
            '0.rhel.pool.ntp.org',
            '1.rhel.pool.ntp.org',
            '2.rhel.pool.ntp.org'
        ])

        self.description = (
            f"Configure NTP server pools:\n"
            f"  - Add the following NTP pools to chrony:\n"
            + "\n".join(f"    - {pool}" for pool in self.ntp_pools) +
            f"\n  - Restart chronyd after changes"
        )

        self.hints = [
            "Edit /etc/chrony.conf",
            "Add lines: pool <server> iburst",
            "iburst speeds up initial sync (good practice, not scored)",
            "Restart: systemctl restart chronyd",
            "Verify: chronyc sources -v"
        ]

        return self

    def validate(self):
        """Validate NTP pool configuration."""
        checks = []
        total_points = 0

        # Check 1: chronyd running (3 points)
        result = execute_safe(['systemctl', 'is-active', 'chronyd'])
        if result.success and result.stdout.strip() == 'active':
            checks.append(ValidationCheck(
                name="chronyd_active",
                passed=True,
                points=3,
                message="chronyd is running"
            ))
            total_points += 3
        else:
            checks.append(ValidationCheck(
                name="chronyd_active",
                passed=False,
                points=0,
                max_points=3,
                message="chronyd is not running"
            ))

        # Check 2: The requested pools are configured (7 points). The question
        # no longer dictates the directive/options, so accept any config line
        # naming the pools (pool or server, with or without iburst) — what the
        # real exam grades is that the box syncs from the given pools.
        pools_found = 0
        for pool in self.ntp_pools:
            if validate_file_contains('/etc/chrony.conf', pool):
                pools_found += 1

        if pools_found >= len(self.ntp_pools):
            checks.append(ValidationCheck(
                name="pools_configured",
                passed=True,
                points=7,
                message=f"All {pools_found} NTP pools configured"
            ))
            total_points += 7
        elif pools_found >= 1:
            pts = 4 if pools_found >= 2 else 2
            checks.append(ValidationCheck(
                name="pools_configured",
                passed=False,
                points=pts,
                max_points=7,
                message=f"Only {pools_found} of {len(self.ntp_pools)} requested pools configured"
            ))
            total_points += pts
        else:
            checks.append(ValidationCheck(
                name="pools_configured",
                passed=False,
                points=0,
                max_points=7,
                message="None of the requested pools found in config"
            ))

        passed = total_points >= (self.points * 0.7)
        return ValidationResult(self.id, passed, total_points, self.points, checks)
