"""
DeviceManager - Automatic resource cleanup for RHCSA Simulator v2.0.0

This module provides centralized management of practice resources with
automatic cleanup between tasks. No more manual disk wiping!

Usage:
    from device import get_device_manager

    dm = get_device_manager()
    with dm.task_context("task_001") as ctx:
        device = dm.get_practice_device()
        # User completes task...
    # Resources automatically cleaned up here
"""

import logging
import subprocess
import time
import os
from dataclasses import dataclass, field
from typing import List, Dict, Optional, Set, Tuple, Any
from enum import Enum
from contextlib import contextmanager

from utils.system_id import system_vgs as get_system_vgs, is_system_disk


logger = logging.getLogger(__name__)


class ResourceType(Enum):
    """Types of resources that can be tracked and cleaned up."""
    LOOP_DEVICE = "loop_device"
    PHYSICAL_VOLUME = "physical_volume"
    VOLUME_GROUP = "volume_group"
    LOGICAL_VOLUME = "logical_volume"
    FILESYSTEM = "filesystem"
    MOUNT_POINT = "mount_point"
    SWAP = "swap"
    FSTAB_ENTRY = "fstab_entry"
    USER = "user"
    GROUP = "group"
    FILE = "file"
    DIRECTORY = "directory"
    CRON_JOB = "cron_job"


# Cleanup order - lower numbers cleaned first
CLEANUP_ORDER = {
    ResourceType.MOUNT_POINT: 10,       # Unmount first
    ResourceType.SWAP: 15,              # Deactivate swap
    ResourceType.FSTAB_ENTRY: 20,       # Remove persistence
    ResourceType.LOGICAL_VOLUME: 30,    # Remove LVs
    ResourceType.VOLUME_GROUP: 40,      # Then VGs
    ResourceType.PHYSICAL_VOLUME: 50,   # Then PVs
    ResourceType.LOOP_DEVICE: 55,       # Loop devices
    ResourceType.FILESYSTEM: 25,        # FS signatures
    ResourceType.USER: 70,              # Users
    ResourceType.GROUP: 75,             # Groups after users
    ResourceType.FILE: 80,              # Files
    ResourceType.DIRECTORY: 85,         # Directories
    ResourceType.CRON_JOB: 90,          # Cron jobs
}


@dataclass
class TrackedResource:
    """A resource created during a task that needs cleanup."""
    resource_type: ResourceType
    identifier: str  # Device path, username, mount point, etc.
    task_id: str
    created_at: float = field(default_factory=time.time)
    cleanup_order: int = 50
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        if self.cleanup_order == 50:
            self.cleanup_order = CLEANUP_ORDER.get(self.resource_type, 50)


class DeviceManager:
    """
    Centralized device and resource management for RHCSA Simulator.

    Handles:
    - Practice device allocation
    - Resource tracking (LVM, mounts, users, etc.)
    - Automatic cleanup between tasks
    - Session state persistence

    This is a singleton - use get_device_manager() to get the instance.
    """

    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return
        self._initialized = True

        self.logger = logging.getLogger(__name__)
        self._tracked_resources: List[TrackedResource] = []
        self._practice_device: Optional[str] = None
        self._cleanup_enabled = True
        self._dry_run = False
        self._current_task_id: Optional[str] = None

        # Detect practice device on init
        self._detect_practice_device()

    def _detect_practice_device(self) -> Optional[str]:
        """Detect the practice device (empty disk or practice PV)."""
        system_vgs = get_system_vgs()

        try:
            # Use lsblk to find available disks
            result = subprocess.run(
                ['lsblk', '-dpno', 'NAME,TYPE,SIZE'],
                capture_output=True, text=True, timeout=10
            )

            if result.returncode != 0:
                return None

            candidates = []

            for line in result.stdout.strip().splitlines():
                if not line.strip():
                    continue
                parts = line.split()
                if len(parts) >= 2:
                    device = parts[0]
                    dtype = parts[1]

                    if dtype != 'disk':
                        continue

                    # Skip the disk(s) the OS actually lives on. Determined
                    # from the live mounts, not from the device name — the OS
                    # is not always on the first disk.
                    if is_system_disk(device):
                        continue

                    # Skip CD-ROM/removable
                    if 'sr' in device or 'fd' in device:
                        continue

                    # Skip boot/secondary system disks
                    if device in ['/dev/sdb', '/dev/sdc']:
                        # Check if it's part of a system VG
                        pv_check = subprocess.run(
                            ['pvs', '--noheadings', '-o', 'pv_name,vg_name', device],
                            capture_output=True, text=True, timeout=5
                        )
                        if pv_check.returncode == 0:
                            vg_name = pv_check.stdout.split()[-1] if pv_check.stdout.split() else ''
                            if vg_name in system_vgs:
                                continue

                    # This is a candidate practice device
                    candidates.append(device)

            # Prioritize: empty disks first, then disks with non-system PVs
            for device in candidates:
                # Check if disk has partitions or children
                part_result = subprocess.run(
                    ['lsblk', '-no', 'NAME', device],
                    capture_output=True, text=True, timeout=5
                )
                children = [l.strip() for l in part_result.stdout.strip().splitlines() if l.strip()]
                has_children = len(children) > 1

                # Check if it's a PV and what VG it belongs to
                pv_check = subprocess.run(
                    ['pvs', '--noheadings', '-o', 'pv_name,vg_name', device],
                    capture_output=True, text=True, timeout=5
                )

                is_pv = device in pv_check.stdout
                vg_name = ''
                if is_pv and pv_check.stdout.strip():
                    parts = pv_check.stdout.strip().split()
                    if len(parts) >= 2:
                        vg_name = parts[-1]

                # Use this device if:
                # 1. It's empty (no children, not a PV), OR
                # 2. It's a PV in a non-system VG (practice VG)
                if not has_children and not is_pv:
                    self._practice_device = device
                    self.logger.info(f"Detected practice device: {device} (empty)")
                    return device
                elif is_pv and vg_name and vg_name not in system_vgs:
                    self._practice_device = device
                    self.logger.info(f"Detected practice device: {device} (has practice LVM: {vg_name})")
                    return device

            # Fallback: use /dev/sdd if it exists
            for device in candidates:
                if 'sdd' in device:
                    self._practice_device = device
                    self.logger.info(f"Detected practice device: {device} (fallback)")
                    return device

            return None
        except Exception as e:
            self.logger.warning(f"Error detecting practice device: {e}")
            return None

    def get_practice_device(self) -> Optional[str]:
        """Get the practice device path."""
        if not self._practice_device:
            self._detect_practice_device()
        return self._practice_device

    # ===== Resource Tracking =====

    def track_resource(self, resource_type: ResourceType, identifier: str,
                       task_id: Optional[str] = None, **metadata):
        """
        Track a resource for later cleanup.

        Args:
            resource_type: Type of resource (LV, mount, user, etc.)
            identifier: Unique identifier (path, name, etc.)
            task_id: Task that created this resource (uses current if None)
            metadata: Additional info for cleanup (e.g., vg_name for LV)
        """
        task = task_id or self._current_task_id or "unknown"

        # Check if already tracked
        for res in self._tracked_resources:
            if res.resource_type == resource_type and res.identifier == identifier:
                self.logger.debug(f"Resource already tracked: {resource_type.value} {identifier}")
                return

        resource = TrackedResource(
            resource_type=resource_type,
            identifier=identifier,
            task_id=task,
            metadata=metadata
        )
        self._tracked_resources.append(resource)
        self.logger.info(f"Tracking {resource_type.value}: {identifier} for task {task}")

    def untrack_resource(self, resource_type: ResourceType, identifier: str):
        """Remove a resource from tracking."""
        self._tracked_resources = [
            r for r in self._tracked_resources
            if not (r.resource_type == resource_type and r.identifier == identifier)
        ]

    def get_tracked_resources(self, task_id: Optional[str] = None) -> List[TrackedResource]:
        """Get tracked resources, optionally filtered by task."""
        if task_id:
            return [r for r in self._tracked_resources if r.task_id == task_id]
        return self._tracked_resources.copy()

    # ===== Auto-Detection of Created Resources =====

    def scan_for_new_resources(self, task_id: str):
        """
        Scan the system for resources that might have been created.
        Called after task validation to catch any untracked resources.
        Scans ALL non-system LVM, not just the practice device.
        """
        system_vgs = get_system_vgs()
        device = self.get_practice_device()

        # Check for ALL PVs on non-system VGs (including loop devices)
        try:
            result = subprocess.run(
                ['pvs', '--noheadings', '-o', 'pv_name,vg_name'],
                capture_output=True, text=True, timeout=5
            )
            for line in result.stdout.strip().splitlines():
                parts = line.split()
                if len(parts) >= 2:
                    pv_name = parts[0].strip()
                    vg_name = parts[1].strip()
                    # Track if it's on practice device, loop device, or non-system VG
                    is_practice = (device and device in pv_name) or '/dev/loop' in pv_name
                    is_nonsystem_vg = vg_name not in system_vgs
                    if is_practice or is_nonsystem_vg:
                        self.track_resource(ResourceType.PHYSICAL_VOLUME, pv_name, task_id)
                        if vg_name and vg_name not in system_vgs:
                            self.track_resource(ResourceType.VOLUME_GROUP, vg_name, task_id)
        except Exception as e:
            self.logger.debug(f"Error scanning PVs: {e}")

        # Check for VGs
        try:
            result = subprocess.run(
                ['vgs', '--noheadings', '-o', 'vg_name'],
                capture_output=True, text=True, timeout=5
            )
            system_vgs = get_system_vgs()
            for line in result.stdout.strip().splitlines():
                vg = line.strip()
                if vg and vg not in system_vgs:
                    self.track_resource(ResourceType.VOLUME_GROUP, vg, task_id)
        except Exception:
            pass

        # Check for LVs in non-system VGs
        try:
            result = subprocess.run(
                ['lvs', '--noheadings', '-o', 'lv_name,vg_name'],
                capture_output=True, text=True, timeout=5
            )
            system_vgs = get_system_vgs()
            for line in result.stdout.strip().splitlines():
                parts = line.split()
                if len(parts) >= 2:
                    lv_name = parts[0].strip()
                    vg_name = parts[1].strip()
                    if vg_name not in system_vgs:
                        self.track_resource(
                            ResourceType.LOGICAL_VOLUME,
                            f"/dev/{vg_name}/{lv_name}",
                            task_id,
                            vg_name=vg_name,
                            lv_name=lv_name
                        )
        except Exception:
            pass

        # Check for mounts on practice devices, loop devices, or non-system VG LVs
        try:
            result = subprocess.run(
                ['mount'], capture_output=True, text=True, timeout=5
            )
            for line in result.stdout.splitlines():
                # Skip system mounts
                if any(x in line for x in ['/boot', '/ type', '/home type', '/var type']):
                    continue

                should_track = False
                # Check for practice device
                if device and device in line:
                    should_track = True
                # Check for loop device mounts
                if '/dev/loop' in line:
                    should_track = True
                # Check for mapper devices from non-system VGs
                if '/dev/mapper/' in line:
                    mapper_name = line.split()[0].replace('/dev/mapper/', '')
                    vg_part = mapper_name.split('-')[0]
                    if vg_part not in system_vgs:
                        should_track = True

                if should_track:
                    parts = line.split()
                    if len(parts) >= 3:
                        mount_point = parts[2]
                        if mount_point.startswith('/mnt/') or mount_point.startswith('/srv/'):
                            self.track_resource(ResourceType.MOUNT_POINT, mount_point, task_id)
        except Exception:
            pass

        # Check for active swap on any non-system device
        try:
            result = subprocess.run(
                ['swapon', '--show=NAME', '--noheadings'],
                capture_output=True, text=True, timeout=5
            )
            for line in result.stdout.strip().splitlines():
                swap_dev = line.strip()
                should_track = False
                if device and device in swap_dev:
                    should_track = True
                if '/dev/loop' in swap_dev:
                    should_track = True
                if 'mapper' in swap_dev:
                    mapper_name = swap_dev.replace('/dev/mapper/', '')
                    vg_part = mapper_name.split('-')[0]
                    if vg_part not in system_vgs:
                        should_track = True
                if should_track:
                    self.track_resource(ResourceType.SWAP, swap_dev, task_id)
        except Exception:
            pass

    # ===== Cleanup Operations =====

    def cleanup_task_resources(self, task_id: str, force: bool = False) -> bool:
        """
        Clean up all resources created by a specific task.

        Args:
            task_id: Task to clean up
            force: Continue cleanup even on errors

        Returns:
            True if all cleaned successfully
        """
        if not self._cleanup_enabled:
            self.logger.info("Cleanup disabled, skipping")
            return True

        # First scan for any untracked resources
        self.scan_for_new_resources(task_id)

        resources = self.get_tracked_resources(task_id)
        if not resources:
            self.logger.info(f"No resources to clean up for task {task_id}")
            # Still do a safety cleanup of the practice device
            return self._safety_cleanup()

        # Sort by cleanup order
        resources.sort(key=lambda r: r.cleanup_order)

        self.logger.info(f"Cleaning up {len(resources)} resources for task {task_id}")
        all_success = True

        for resource in resources:
            try:
                success = self._cleanup_resource(resource)
                if success:
                    self.untrack_resource(resource.resource_type, resource.identifier)
                else:
                    all_success = False
                    if not force:
                        self.logger.error(f"Cleanup failed for {resource.identifier}, stopping")
                        break
            except Exception as e:
                self.logger.error(f"Error cleaning {resource.identifier}: {e}")
                all_success = False
                if not force:
                    break

        # Always do safety cleanup at the end
        self._safety_cleanup()

        return all_success

    def cleanup_all_resources(self, force: bool = True) -> bool:
        """Clean up ALL tracked resources."""
        task_ids = set(r.task_id for r in self._tracked_resources)
        all_success = True
        for task_id in task_ids:
            if not self.cleanup_task_resources(task_id, force=force):
                all_success = False
        return all_success

    def _cleanup_resource(self, resource: TrackedResource) -> bool:
        """Clean up a single resource."""
        rtype = resource.resource_type
        identifier = resource.identifier

        if self._dry_run:
            self.logger.info(f"[DRY RUN] Would clean {rtype.value}: {identifier}")
            return True

        self.logger.info(f"Cleaning {rtype.value}: {identifier}")

        try:
            if rtype == ResourceType.MOUNT_POINT:
                return self._cleanup_mount(identifier)
            elif rtype == ResourceType.SWAP:
                return self._cleanup_swap(identifier)
            elif rtype == ResourceType.FSTAB_ENTRY:
                return self._cleanup_fstab(identifier)
            elif rtype == ResourceType.LOGICAL_VOLUME:
                return self._cleanup_lv(identifier, resource.metadata)
            elif rtype == ResourceType.VOLUME_GROUP:
                return self._cleanup_vg(identifier)
            elif rtype == ResourceType.PHYSICAL_VOLUME:
                return self._cleanup_pv(identifier)
            elif rtype == ResourceType.USER:
                return self._cleanup_user(identifier)
            elif rtype == ResourceType.GROUP:
                return self._cleanup_group(identifier)
            elif rtype == ResourceType.FILE:
                return self._cleanup_file(identifier)
            elif rtype == ResourceType.DIRECTORY:
                return self._cleanup_directory(identifier)
            else:
                self.logger.warning(f"Unknown resource type: {rtype}")
                return False
        except Exception as e:
            self.logger.error(f"Failed to clean {rtype.value} {identifier}: {e}")
            return False

    def _safety_cleanup(self) -> bool:
        """
        Safety cleanup of ALL practice resources - catches anything missed.
        Cleans: practice device, loop devices, any non-system LVM.
        """
        device = self.get_practice_device()
        self.logger.info(f"Running safety cleanup (practice device: {device})")
        success = True

        # Collect all devices to clean (practice device + loop devices with practice LVM)
        devices_to_clean = set()
        if device:
            devices_to_clean.add(device)

        # Find loop devices that have non-system LVM
        system_vgs = get_system_vgs()
        try:
            result = subprocess.run(
                ['pvs', '--noheadings', '-o', 'pv_name,vg_name'],
                capture_output=True, text=True, timeout=5
            )
            for line in result.stdout.strip().splitlines():
                parts = line.split()
                if len(parts) >= 2:
                    pv_name = parts[0].strip()
                    vg_name = parts[1].strip()
                    # If this PV is on a loop device and not a system VG, clean it
                    if '/dev/loop' in pv_name and vg_name not in system_vgs:
                        devices_to_clean.add(pv_name)
                    # Also add any non-system PV on other devices
                    elif vg_name not in system_vgs:
                        devices_to_clean.add(pv_name)
        except Exception:
            pass

        # Last line of defence before pvremove/wipefs: drop anything that is
        # (or sits on) a disk the OS lives on. The VG-name checks above should
        # already have excluded these, but steps 5 and 6 below are
        # unrecoverable, so they get an independent check.
        protected = {dev for dev in devices_to_clean if is_system_disk(dev)}
        if protected:
            self.logger.warning(
                f"Refusing to clean system device(s): {sorted(protected)}")
            devices_to_clean -= protected

        self.logger.info(f"Devices to clean: {devices_to_clean}")

        # 1. Unmount anything on practice devices or mapper devices from non-system VGs
        try:
            result = subprocess.run(['mount'], capture_output=True, text=True, timeout=5)
            for line in result.stdout.splitlines():
                should_unmount = False
                mount_point = None

                # Check if mount is on any device we're cleaning
                for dev in devices_to_clean:
                    if dev in line:
                        should_unmount = True
                        break

                # Check mapper devices for non-system VGs
                if '/dev/mapper/' in line:
                    mapper_name = line.split()[0].replace('/dev/mapper/', '')
                    vg_part = mapper_name.split('-')[0]
                    if vg_part not in system_vgs:
                        should_unmount = True

                if should_unmount:
                    parts = line.split()
                    if len(parts) >= 3:
                        mount_point = parts[2]
                        # Don't unmount system mounts
                        if mount_point in ['/', '/boot', '/home', '/var', '/tmp']:
                            continue
                        subprocess.run(['umount', '-f', mount_point],
                                       capture_output=True, timeout=10)
        except Exception as e:
            self.logger.debug(f"Mount cleanup: {e}")

        # 2. Deactivate any swap on non-system VGs
        system_vgs = get_system_vgs()
        try:
            result = subprocess.run(
                ['swapon', '--show=NAME', '--noheadings'],
                capture_output=True, text=True, timeout=5
            )
            for line in result.stdout.strip().splitlines():
                swap_dev = line.strip()
                should_swapoff = False

                # Check if swap is on our practice device directly
                if device in swap_dev:
                    should_swapoff = True
                # Check if it's a mapper device on a non-system VG
                elif 'mapper' in swap_dev:
                    # Extract VG name from /dev/mapper/vgname-lvname
                    parts = swap_dev.replace('/dev/mapper/', '').split('-')
                    if parts and parts[0] not in system_vgs:
                        should_swapoff = True
                # Check if it's a dm-N device (need to resolve to VG)
                elif '/dev/dm-' in swap_dev:
                    # Try to resolve the dm device to its LV
                    dm_resolve = subprocess.run(
                        ['dmsetup', 'info', '-c', '--noheadings', '-o', 'name', swap_dev],
                        capture_output=True, text=True, timeout=5
                    )
                    if dm_resolve.returncode == 0:
                        dm_name = dm_resolve.stdout.strip()
                        # dm_name is like "vg_test-lv_test"
                        if dm_name:
                            vg_part = dm_name.split('-')[0]
                            if vg_part not in system_vgs:
                                should_swapoff = True

                if should_swapoff:
                    subprocess.run(['swapoff', swap_dev], capture_output=True, timeout=10)
        except Exception:
            pass

        # 3. Remove non-system LVs
        try:
            result = subprocess.run(
                ['lvs', '--noheadings', '-o', 'lv_path,vg_name'],
                capture_output=True, text=True, timeout=5
            )
            system_vgs = get_system_vgs()
            for line in result.stdout.strip().splitlines():
                parts = line.split()
                if len(parts) >= 2:
                    lv_path = parts[0].strip()
                    vg_name = parts[1].strip()
                    if vg_name not in system_vgs:
                        subprocess.run(
                            ['lvremove', '-f', lv_path],
                            capture_output=True, timeout=15
                        )
        except Exception:
            pass

        # 4. Remove non-system VGs
        try:
            result = subprocess.run(
                ['vgs', '--noheadings', '-o', 'vg_name'],
                capture_output=True, text=True, timeout=5
            )
            system_vgs = get_system_vgs()
            for line in result.stdout.strip().splitlines():
                vg = line.strip()
                if vg and vg not in system_vgs:
                    subprocess.run(
                        ['vgremove', '-f', vg],
                        capture_output=True, timeout=15
                    )
        except Exception:
            pass

        # 5. Remove PVs from all practice devices (including loop devices)
        for dev in devices_to_clean:
            try:
                subprocess.run(
                    ['pvremove', '-f', '-y', dev],
                    capture_output=True, timeout=15
                )
            except Exception:
                pass

        # 6. Wipe device signatures on all practice devices
        for dev in devices_to_clean:
            try:
                subprocess.run(
                    ['wipefs', '-a', dev],
                    capture_output=True, timeout=15
                )
            except Exception:
                pass

        # 7. Clean up fstab entries for practice mounts
        self._cleanup_practice_fstab_entries()

        self.logger.info("Safety cleanup complete")
        return success

    def _cleanup_mount(self, mount_point: str) -> bool:
        """Unmount a filesystem."""
        result = subprocess.run(
            ['umount', '-f', mount_point],
            capture_output=True, timeout=15
        )
        return result.returncode == 0

    def _cleanup_swap(self, device: str) -> bool:
        """Deactivate swap."""
        result = subprocess.run(
            ['swapoff', device],
            capture_output=True, timeout=15
        )
        return result.returncode == 0

    def _cleanup_fstab(self, identifier: str) -> bool:
        """Remove an entry from /etc/fstab."""
        return self._remove_fstab_entry(identifier)

    def _cleanup_lv(self, lv_path: str, metadata: Dict) -> bool:
        """Remove a logical volume."""
        # First unmount if mounted
        result = subprocess.run(['mount'], capture_output=True, text=True, timeout=5)
        for line in result.stdout.splitlines():
            if lv_path in line or (metadata.get('vg_name') and metadata.get('lv_name') and
                                    f"{metadata['vg_name']}-{metadata['lv_name']}" in line):
                parts = line.split()
                if len(parts) >= 3:
                    subprocess.run(['umount', '-f', parts[2]], capture_output=True, timeout=10)

        # Deactivate swap if this LV is swap
        subprocess.run(['swapoff', lv_path], capture_output=True, timeout=5)

        # Remove the LV
        result = subprocess.run(
            ['lvremove', '-f', lv_path],
            capture_output=True, timeout=15
        )
        return result.returncode == 0

    def _cleanup_vg(self, vg_name: str) -> bool:
        """Remove a volume group."""
        result = subprocess.run(
            ['vgremove', '-f', vg_name],
            capture_output=True, timeout=15
        )
        return result.returncode == 0

    def _cleanup_pv(self, device: str) -> bool:
        """Remove a physical volume."""
        result = subprocess.run(
            ['pvremove', '-f', '-y', device],
            capture_output=True, timeout=15
        )
        return result.returncode == 0

    def _cleanup_user(self, username: str) -> bool:
        """Remove a user."""
        # Don't remove system users
        if username in ['root', 'austin', 'nobody', 'systemd-network']:
            return True
        result = subprocess.run(
            ['userdel', '-rf', username],
            capture_output=True, timeout=15
        )
        return result.returncode == 0

    def _cleanup_group(self, groupname: str) -> bool:
        """Remove a group."""
        # Don't remove system groups
        if groupname in ['root', 'wheel', 'users', 'nobody']:
            return True
        result = subprocess.run(
            ['groupdel', groupname],
            capture_output=True, timeout=10
        )
        return result.returncode == 0

    def _cleanup_file(self, filepath: str) -> bool:
        """Remove a file."""
        try:
            if os.path.exists(filepath):
                os.remove(filepath)
            return True
        except Exception:
            return False

    def _cleanup_directory(self, dirpath: str) -> bool:
        """Remove a directory."""
        # Don't remove system directories
        if dirpath in ['/', '/home', '/root', '/etc', '/var', '/tmp', '/mnt']:
            return True
        try:
            if os.path.exists(dirpath):
                import shutil
                shutil.rmtree(dirpath)
            return True
        except Exception:
            return False

    def _remove_fstab_entry(self, identifier: str) -> bool:
        """Remove an entry from /etc/fstab matching the identifier."""
        try:
            with open('/etc/fstab', 'r') as f:
                lines = f.readlines()

            new_lines = []
            for line in lines:
                # Keep the line if it doesn't match our identifier
                if identifier not in line:
                    new_lines.append(line)
                else:
                    self.logger.info(f"Removing fstab entry: {line.strip()}")

            with open('/etc/fstab', 'w') as f:
                f.writelines(new_lines)

            return True
        except Exception as e:
            self.logger.error(f"Failed to clean fstab: {e}")
            return False

    def _cleanup_practice_fstab_entries(self):
        """Remove all practice-related entries from fstab."""
        device = self.get_practice_device()
        if not device:
            return

        try:
            with open('/etc/fstab', 'r') as f:
                lines = f.readlines()

            new_lines = []
            device_basename = device.split('/')[-1]  # e.g., 'sdd' from '/dev/sdd'

            for line in lines:
                # Keep system entries
                if line.strip().startswith('#') or not line.strip():
                    new_lines.append(line)
                    continue

                # Skip entries related to practice
                skip = False
                # Check for practice device
                if device in line or device_basename in line:
                    skip = True
                # Check for practice mount points
                if any(x in line for x in ['/mnt/lvm', '/mnt/data', '/mnt/practice', '/mnt/persistent']):
                    skip = True
                # Check for non-system VGs
                if '/dev/mapper/' in line and not any(x in line for x in ['rl-', 'rl00-', 'rhel-']):
                    skip = True

                if not skip:
                    new_lines.append(line)
                else:
                    self.logger.info(f"Removing practice fstab entry: {line.strip()}")

            with open('/etc/fstab', 'w') as f:
                f.writelines(new_lines)

        except Exception as e:
            self.logger.error(f"Failed to clean practice fstab entries: {e}")

    # ===== Context Manager =====

    @contextmanager
    def task_context(self, task_id: str, auto_cleanup: bool = True):
        """
        Context manager for task execution with automatic cleanup.

        Usage:
            with device_manager.task_context("task_001") as dm:
                device = dm.get_practice_device()
                # User completes task
            # Automatic cleanup happens here

        Args:
            task_id: Unique identifier for the task
            auto_cleanup: Whether to clean up on exit (default True)
        """
        self._current_task_id = task_id
        self.logger.info(f"Starting task context: {task_id}")

        try:
            yield self
        finally:
            self.logger.info(f"Ending task context: {task_id}")
            if auto_cleanup and self._cleanup_enabled:
                self.cleanup_task_resources(task_id, force=True)
            self._current_task_id = None

    # ===== Configuration =====

    def enable_cleanup(self):
        """Enable automatic cleanup."""
        self._cleanup_enabled = True

    def disable_cleanup(self):
        """Disable automatic cleanup (for debugging)."""
        self._cleanup_enabled = False

    def set_dry_run(self, dry_run: bool):
        """Enable/disable dry run mode."""
        self._dry_run = dry_run

    # ===== State =====

    def get_state(self) -> Dict:
        """Get current state for session save."""
        return {
            'practice_device': self._practice_device,
            'tracked_resources': [
                {
                    'type': r.resource_type.value,
                    'identifier': r.identifier,
                    'task_id': r.task_id,
                    'metadata': r.metadata
                }
                for r in self._tracked_resources
            ]
        }

    def get_statistics(self) -> Dict:
        """Get device manager statistics."""
        return {
            'practice_device': self._practice_device,
            'tracked_resources': len(self._tracked_resources),
            'cleanup_enabled': self._cleanup_enabled,
            'resources_by_type': {
                rtype.value: len([r for r in self._tracked_resources if r.resource_type == rtype])
                for rtype in ResourceType
            }
        }


# Global instance getter
_device_manager: Optional[DeviceManager] = None


def get_device_manager() -> DeviceManager:
    """Get the global DeviceManager instance."""
    global _device_manager
    if _device_manager is None:
        _device_manager = DeviceManager()
    return _device_manager
