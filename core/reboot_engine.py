"""
Reboot simulation engine for RHCSA Simulator v4.0.0

The killer feature. Simulates exam grading after reboot:
1. Check boot-critical configs (fstab, default target, GRUB)
2. If boot fails -> score 0/300
3. If boot succeeds -> re-validate all persistence tasks
4. Report which tasks lost points due to non-persistent configs
"""

import logging
from core.validator import ValidationEngine, RebootResult, ValidationResult
from validators.safe_executor import execute_safe


logger = logging.getLogger(__name__)


class RebootEngine:
    """Simulates system reboot and persistence validation."""

    def __init__(self):
        self.validator = ValidationEngine()

    def simulate_reboot(self, tasks, initial_results):
        """
        Simulate a system reboot and re-validate persistence tasks.

        Args:
            tasks: List of task instances from the exam
            initial_results: Dict mapping task_id -> ValidationResult from initial validation

        Returns:
            RebootResult with boot status and persistence results
        """
        logger.info("Starting reboot simulation...")

        # Phase 1: Check boot-critical configurations
        boot_success, boot_blockers = self._check_boot_critical()

        if not boot_success:
            logger.warning(f"Boot failed! Blockers: {boot_blockers}")
            return RebootResult(
                boot_success=False,
                boot_blockers=boot_blockers,
            )

        # Phase 2: Re-validate persistence tasks
        persistence_results = {}
        tasks_lost_points = []

        for task in tasks:
            if not task.requires_persistence:
                continue

            initial = initial_results.get(task.id)
            if not initial or not initial.passed:
                continue

            persistence_result = self.validator.validate_persistence(task)
            persistence_results[task.id] = persistence_result

            if not persistence_result.passed:
                tasks_lost_points.append(task.id)
                logger.info(
                    f"Task {task.id} lost points: passed initially but "
                    f"failed persistence check"
                )

        return RebootResult(
            boot_success=True,
            persistence_results=persistence_results,
            tasks_lost_points=tasks_lost_points,
        )

    def _check_boot_critical(self):
        """
        Check boot-critical configurations.

        Returns:
            tuple: (boot_success: bool, blockers: list of str)
        """
        blockers = []

        # Check 1: Validate /etc/fstab
        fstab_ok = self._check_fstab()
        if not fstab_ok:
            blockers.append("Invalid /etc/fstab entries would prevent boot")

        # Check 2: Default target exists
        target_ok = self._check_default_target()
        if not target_ok:
            blockers.append("Default systemd target is invalid or missing")

        # Check 3: GRUB config is valid
        grub_ok = self._check_grub()
        if not grub_ok:
            blockers.append("GRUB configuration is broken")

        boot_success = len(blockers) == 0
        return boot_success, blockers

    def _check_fstab(self):
        """Validate fstab using findmnt --verify."""
        result = execute_safe(['findmnt', '--verify', '--tab-file', '/etc/fstab'])
        if result.success:
            # findmnt --verify returns 0 if all entries are valid
            # Check stderr for warnings
            if result.stderr and 'error' in result.stderr.lower():
                logger.warning(f"fstab verification warnings: {result.stderr}")
                return False
            return True

        # If findmnt fails, try basic cat check
        result = execute_safe(['cat', '/etc/fstab'])
        if not result.success:
            return False

        # Check for obviously broken entries (devices that don't exist)
        for line in result.stdout.split('\n'):
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            parts = line.split()
            if len(parts) < 4:
                continue
            device = parts[0]
            mount = parts[1]
            # Skip special mounts
            if device in ('proc', 'sysfs', 'devpts', 'tmpfs', 'devtmpfs'):
                continue
            if mount in ('swap',) or parts[2] == 'swap':
                continue
            # Check nofail option
            options = parts[3] if len(parts) > 3 else ''
            if 'nofail' in options:
                continue
            # UUID-based entries - verify UUID exists
            if device.startswith('UUID='):
                uuid = device.split('=', 1)[1]
                blkid_result = execute_safe(['blkid', '-U', uuid])
                if not blkid_result.success:
                    logger.warning(f"fstab: UUID {uuid} not found for {mount}")
                    return False

        return True

    def _check_default_target(self):
        """Check that default systemd target is valid."""
        result = execute_safe(['systemctl', 'get-default'])
        if not result.success:
            return False
        target = result.stdout.strip()
        valid_targets = [
            'multi-user.target', 'graphical.target',
            'rescue.target', 'emergency.target',
        ]
        if target not in valid_targets:
            logger.warning(f"Invalid default target: {target}")
            return False
        return True

    def _check_grub(self):
        """Check that GRUB configuration is intact."""
        # Check grub.cfg exists. On RHEL 9/10 the layout is unified and this
        # is the canonical path for BIOS and UEFI alike.
        result = execute_safe(['test', '-f', '/boot/grub2/grub.cfg'])
        if result.success:
            return True

        # Older/odd UEFI layouts keep it under a vendor directory named after
        # the distro. That name was previously hardcoded to 'redhat' then
        # 'rocky', so AlmaLinux (/boot/efi/EFI/almalinux) failed this check
        # and every boot task on Alma reported a boot failure. Glob instead of
        # guessing names one at a time.
        from utils.system_id import efi_grub_configs
        for cfg in efi_grub_configs():
            if execute_safe(['test', '-f', cfg]).success:
                return True
        return False

    def get_reboot_report(self, reboot_result, tasks):
        """Generate a human-readable reboot simulation report."""
        lines = []
        lines.append("=" * 60)
        lines.append("REBOOT SIMULATION RESULTS")
        lines.append("=" * 60)

        if not reboot_result.boot_success:
            lines.append("")
            lines.append("*** SYSTEM FAILED TO BOOT ***")
            lines.append("Score: 0/300 (boot failure = automatic fail)")
            lines.append("")
            lines.append("Boot blockers:")
            for blocker in reboot_result.boot_blockers:
                lines.append(f"  - {blocker}")
            lines.append("")
            lines.append("FIX: Ensure /etc/fstab is valid, default target exists,")
            lines.append("     and GRUB configuration is intact.")
        else:
            lines.append("")
            lines.append("System booted successfully.")
            lines.append("")

            persistence_count = len(reboot_result.persistence_results)
            passed_count = sum(
                1 for r in reboot_result.persistence_results.values() if r.passed
            )
            failed_count = persistence_count - passed_count

            lines.append(f"Persistence tasks checked: {persistence_count}")
            lines.append(f"  Passed: {passed_count}")
            lines.append(f"  Failed: {failed_count}")

            if reboot_result.tasks_lost_points:
                lines.append("")
                lines.append("Tasks that LOST POINTS (not persistent):")
                for task_id in reboot_result.tasks_lost_points:
                    task = next((t for t in tasks if t.id == task_id), None)
                    if task:
                        lines.append(
                            f"  - {task_id} ({task.category}): "
                            f"Passed initially but failed after reboot"
                        )

        return "\n".join(lines)


_reboot_engine = None


def get_reboot_engine():
    global _reboot_engine
    if _reboot_engine is None:
        _reboot_engine = RebootEngine()
    return _reboot_engine
