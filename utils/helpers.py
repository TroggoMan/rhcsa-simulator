"""
Helper utility functions for RHCSA Simulator.
"""

import logging
import os
import sys
import uuid
from datetime import timedelta

logger = logging.getLogger(__name__)


def check_root():
    """
    Check if the script is running with root privileges.

    Returns:
        bool: True if running as root, False otherwise
    """
    return os.geteuid() == 0


def require_root():
    """
    Require root privileges to continue. Exit if not root.
    """
    if not check_root():
        print("Error: This application requires root privileges.")
        print("Please run with: sudo rhcsa-simulator")
        sys.exit(1)


def generate_id(prefix=""):
    """
    Generate a unique ID with optional prefix.

    Args:
        prefix (str): Optional prefix for the ID

    Returns:
        str: Unique ID string
    """
    unique_id = str(uuid.uuid4())[:8]
    if prefix:
        return f"{prefix}_{unique_id}"
    return unique_id


def format_time(seconds):
    """
    Format seconds into human-readable time string.

    Args:
        seconds (int): Number of seconds

    Returns:
        str: Formatted time string (e.g., "2h 30m 15s")
    """
    if seconds < 0:
        return "0s"

    hours = seconds // 3600
    minutes = (seconds % 3600) // 60
    secs = seconds % 60

    parts = []
    if hours > 0:
        parts.append(f"{hours}h")
    if minutes > 0:
        parts.append(f"{minutes}m")
    if secs > 0 or not parts:
        parts.append(f"{secs}s")

    return " ".join(parts)


def format_timedelta(td):
    """
    Format a timedelta into human-readable string.

    Args:
        td (timedelta): Time delta object

    Returns:
        str: Formatted time string
    """
    total_seconds = int(td.total_seconds())
    return format_time(total_seconds)


def parse_percentage(value):
    """
    Parse a percentage value from various formats.

    Args:
        value: String or number representing a percentage

    Returns:
        float: Percentage as decimal (0.0-1.0)
    """
    if isinstance(value, (int, float)):
        if value > 1:
            return value / 100.0
        return float(value)

    if isinstance(value, str):
        value = value.strip().rstrip('%')
        try:
            num = float(value)
            if num > 1:
                return num / 100.0
            return num
        except ValueError:
            return 0.0

    return 0.0

def confirm_action(prompt, default=False):
    """
    Ask user for confirmation.

    Args:
        prompt (str): Confirmation prompt
        default (bool): Default value if user just presses Enter

    Returns:
        bool: True if user confirms, False otherwise
    """
    suffix = " [Y/n]: " if default else " [y/N]: "
    while True:
        try:
            response = input(prompt + suffix).strip().lower()

            if not response:
                return default
            if response in ['y', 'yes', 'д', 'да']:
                return True
            if response in ['n', 'no', 'н', 'нет']:
                return False

            print("Please answer y or n.")

        except UnicodeDecodeError:
            print("\n[!] Input encoding error (appears to be a corrupted character or a Russian keyboard layout). Please try again.")
        except (EOFError, KeyboardInterrupt):
            print()
            return default

def select_task_count(default=5, minimum=4, maximum=20):
    """Ask how many tasks this session should include (clamped to a sane
    range). Shared by quick practice, practice, and adaptive modes."""
    prompt = f"How many tasks this session? ({minimum}-{maximum}) [{default}]: "
    while True:
        raw = input(prompt).strip()
        if not raw:
            return default
        try:
            n = int(raw)
        except ValueError:
            print("Please enter a whole number.")
            continue
        if n < minimum:
            print(f"Minimum is {minimum}.")
            continue
        if n > maximum:
            print(f"Maximum is {maximum}.")
            continue
        return n


def get_terminal_width():
    """
    Get the current terminal width.

    Returns:
        int: Terminal width in characters (default 80)
    """
    try:
        import shutil
        return shutil.get_terminal_size((80, 20)).columns
    except:
        return 80


def truncate_string(text, max_length, suffix="..."):
    """
    Truncate a string to maximum length.

    Args:
        text (str): Text to truncate
        max_length (int): Maximum length
        suffix (str): Suffix to add if truncated

    Returns:
        str: Truncated string
    """
    if len(text) <= max_length:
        return text
    return text[:max_length - len(suffix)] + suffix


def pluralize(count, singular, plural=None):
    """
    Return singular or plural form based on count.

    Args:
        count (int): Count value
        singular (str): Singular form
        plural (str): Plural form (default: singular + 's')

    Returns:
        str: Appropriate form
    """
    if plural is None:
        plural = singular + 's'
    return singular if count == 1 else plural


def format_list(items, conjunction="and"):
    """
    Format a list of items as a comma-separated string with conjunction.

    Args:
        items (list): List of items
        conjunction (str): Conjunction word (default: "and")

    Returns:
        str: Formatted string
    """
    if not items:
        return ""
    if len(items) == 1:
        return str(items[0])
    if len(items) == 2:
        return f"{items[0]} {conjunction} {items[1]}"
    return ", ".join(str(item) for item in items[:-1]) + f", {conjunction} {items[-1]}"


def safe_divide(numerator, denominator, default=0.0):
    """
    Safely divide two numbers, returning default if denominator is zero.

    Args:
        numerator: Numerator value
        denominator: Denominator value
        default: Default value if division by zero

    Returns:
        float: Division result or default
    """
    try:
        if denominator == 0:
            return default
        return numerator / denominator
    except:
        return default


def clamp(value, min_val, max_val):
    """
    Clamp a value between minimum and maximum.

    Args:
        value: Value to clamp
        min_val: Minimum value
        max_val: Maximum value

    Returns:
        Clamped value
    """
    return max(min_val, min(value, max_val))


# =============================================================================
# Practice Device Configuration
# =============================================================================

PRACTICE_DEVICE_CONFIG = '/var/lib/rhcsa-simulator/practice_devices.conf'


def get_practice_device_config():
    """
    Read the saved practice device configuration.
    Returns dict with keys 'mode' ('loop' or 'real') and 'devices' (list).
    Returns None if no config saved.
    """
    if not os.path.exists(PRACTICE_DEVICE_CONFIG):
        return None
    try:
        import json
        with open(PRACTICE_DEVICE_CONFIG) as f:
            return json.load(f)
    except Exception:
        return None


def save_practice_device_config(mode, devices):
    """
    Save the practice device selection to disk.
    mode: 'loop' or 'real'
    devices: list of device paths
    """
    import json
    os.makedirs(os.path.dirname(PRACTICE_DEVICE_CONFIG), exist_ok=True)
    with open(PRACTICE_DEVICE_CONFIG, 'w') as f:
        json.dump({'mode': mode, 'devices': devices}, f)


def wipe_disk(device):
    """
    Completely wipe a disk: deactivate swap/LVM on all partitions,
    remove filesystem signatures, zero out the partition table, and
    tell the kernel to re-read the disk. Leaves a completely raw device.
    Returns (success, list_of_messages).
    """
    import subprocess

    msgs = []

    # 1. Find all partitions on this disk
    part_result = subprocess.run(
        ['lsblk', '-rno', 'NAME', device],
        capture_output=True, text=True, timeout=10
    )
    all_parts = []
    for line in part_result.stdout.strip().splitlines():
        name = line.strip()
        if not name:
            continue
        path = f"/dev/{name}" if not name.startswith('/') else name
        if path != device:
            all_parts.append(path)

    # 2. Deactivate swap and unmount filesystems on all partitions first
    for dev in all_parts + [device]:
        subprocess.run(['swapoff', dev], capture_output=True, timeout=10)
        subprocess.run(['umount', '-f', dev], capture_output=True, timeout=10)

    # 3. Deactivate any LVM VGs that live on this disk before pvremove
    #    (pvremove fails with "PV used by VG" if the VG is still active)
    vgs_result = subprocess.run(
        ['pvs', '--noheadings', '-o', 'vg_name'] + all_parts + [device],
        capture_output=True, text=True, timeout=10
    )
    active_vgs = {v.strip() for v in vgs_result.stdout.splitlines() if v.strip()}
    for vg in active_vgs:
        subprocess.run(['vgchange', '-an', vg], capture_output=True, timeout=10)
        subprocess.run(['vgremove', '-ff', '-y', vg], capture_output=True, timeout=10)

    for dev in all_parts + [device]:
        subprocess.run(['pvremove', '-ff', '-y', dev], capture_output=True, timeout=10)

    # 4. Rescan so the kernel drops stale VG references
    subprocess.run(['vgscan', '--cache'], capture_output=True, timeout=10)

    # 5. Remove all filesystem/LVM/swap signatures from disk and partitions
    for dev in all_parts + [device]:
        subprocess.run(['wipefs', '-a', dev], capture_output=True, timeout=10)

    # 6. Zero out the first and last few MB to destroy partition tables (MBR + GPT)
    try:
        size_result = subprocess.run(
            ['blockdev', '--getsize64', device],
            capture_output=True, text=True, timeout=10
        )
        disk_bytes = int(size_result.stdout.strip())
        # Zero first 2MB (MBR + GPT header)
        subprocess.run(
            ['dd', 'if=/dev/zero', f'of={device}', 'bs=1M', 'count=2', 'oflag=direct'],
            capture_output=True, timeout=30
        )
        # Zero last 1MB (GPT backup header)
        skip_mb = disk_bytes // (1024 * 1024) - 1
        subprocess.run(
            ['dd', 'if=/dev/zero', f'of={device}', 'bs=1M', 'count=1',
             f'seek={skip_mb}', 'oflag=direct'],
            capture_output=True, timeout=30
        )
        msgs.append(f"Partition table wiped on {device}")
    except Exception as e:
        msgs.append(f"Warning: could not zero partition table on {device}: {e}")

    # 7. Tell kernel to re-read
    subprocess.run(['partprobe', device], capture_output=True, timeout=10)
    subprocess.run(['udevadm', 'settle'], capture_output=True, timeout=15)

    msgs.append(f"{device} is now a clean raw device")
    return True, msgs


def list_all_block_devices():
    """
    Return info on all block devices, excluding CD-ROMs and floppies.
    Does NOT filter out system disks — let the user decide.
    Returns list of dicts: {device, size, has_partitions, mounted, is_system}.
    """
    import subprocess

    result = subprocess.run(
        ['lsblk', '-dpno', 'NAME,SIZE,TYPE'],
        capture_output=True, text=True, timeout=10
    )
    if result.returncode != 0:
        return []

    # Find which physical disk(s) back the / mountpoint.
    # Walk lsblk tree: dm-* devices (LVM) list their underlying disk via PKNAME.
    # We collect every device that is an ancestor of the / mountpoint.
    tree_result = subprocess.run(
        ['lsblk', '-rno', 'NAME,PKNAME,MOUNTPOINT'],  # -r = raw, no tree chars
        capture_output=True, text=True, timeout=10
    )
    # Build parent map: name -> pkname
    parent = {}
    root_devs = set()
    for line in tree_result.stdout.splitlines():
        parts = line.split()
        if len(parts) >= 2:
            name = parts[0]
            pkname = parts[1] if parts[1] != name else None
            mnt = parts[2] if len(parts) >= 3 else ''
            parent[name] = pkname
            if mnt == '/':
                root_devs.add(name)

    # Walk up the parent chain from each root device to find the physical disk
    system_disks = set()
    for dev in root_devs:
        cur = dev
        while cur:
            nxt = parent.get(cur)
            if not nxt:
                system_disks.add(f"/dev/{cur}")
                break
            cur = nxt

    devices = []
    for line in result.stdout.strip().splitlines():
        parts = line.split()
        if len(parts) < 3:
            continue
        device, size, dtype = parts[0], parts[1], parts[2]
        if dtype != 'disk':
            continue
        if any(x in device for x in ['sr', 'fd', 'cdrom']):
            continue

        part_result = subprocess.run(
            ['lsblk', '-rno', 'NAME', device],
            capture_output=True, text=True, timeout=5
        )
        children = [l.strip() for l in part_result.stdout.strip().splitlines() if l.strip()]
        has_partitions = len(children) > 1

        mount_result = subprocess.run(
            ['lsblk', '-rno', 'MOUNTPOINT', device],
            capture_output=True, text=True, timeout=5
        )
        all_mounts = [m.strip() for m in mount_result.stdout.strip().splitlines() if m.strip()]
        # Only real filesystem paths count as "mounted" — [SWAP] does not
        fs_mounts = [m for m in all_mounts if m.startswith('/')]
        has_swap = any(m == '[SWAP]' for m in all_mounts)

        devices.append({
            'device': device,
            'size': size,
            'has_partitions': has_partitions,
            'mounted': bool(fs_mounts),
            'has_swap': has_swap,
            'is_system': device in system_disks,
        })

    return devices


# =============================================================================
# LVM Practice Device Helpers
# =============================================================================

def get_available_block_devices():
    """
    Get list of available unused block devices.
    Prioritizes completely empty disks (no partitions) for practice.

    Returns:
        list: List of device paths (e.g., ['/dev/sdd', '/dev/vdb'])
    """
    import subprocess

    try:
        result = subprocess.run(
            ['lsblk', '-dpno', 'NAME,TYPE,SIZE'],
            capture_output=True, text=True, timeout=10
        )

        if result.returncode != 0:
            return []

        empty_disks = []
        unused_disks = []

        for line in result.stdout.strip().splitlines():
            if not line.strip():
                continue
            parts = line.split()
            if len(parts) >= 2:
                device = parts[0]
                dtype = parts[1]

                if dtype != 'disk':
                    continue

                # Skip known system disks
                if any(x in device for x in ['vda', 'sda', 'nvme0n1', 'xvda']):
                    continue

                # Skip CD-ROM/removable
                if 'sr' in device or 'fd' in device:
                    continue

                # Check if disk has any partitions
                part_result = subprocess.run(
                    ['lsblk', '-no', 'NAME', device],
                    capture_output=True, text=True, timeout=5
                )
                children = [l.strip() for l in part_result.stdout.strip().splitlines() if l.strip()]
                has_partitions = len(children) > 1

                if not has_partitions:
                    # Completely empty disk - check not a PV
                    pv_check = subprocess.run(
                        ['pvs', '--noheadings', '-o', 'pv_name'],
                        capture_output=True, text=True, timeout=5
                    )
                    if device not in pv_check.stdout:
                        empty_disks.append(device)
                else:
                    # Has partitions - check if used by LVM
                    pv_check = subprocess.run(
                        ['pvs', '--noheadings', '-o', 'pv_name'],
                        capture_output=True, text=True, timeout=5
                    )
                    disk_basename = device.split('/')[-1]
                    if disk_basename not in pv_check.stdout:
                        mount_check = subprocess.run(
                            ['lsblk', '-no', 'MOUNTPOINT', device],
                            capture_output=True, text=True, timeout=5
                        )
                        mounts = [m for m in mount_check.stdout.strip().splitlines() if m.strip()]
                        if not mounts:
                            unused_disks.append(device)

        return empty_disks + unused_disks
    except Exception as e:
        return []


def partition_device(device, number):
    """Build the partition device path for `device` using the kernel's naming
    rule: insert a 'p' before the partition number only when the device name
    ends in a digit.

        /dev/sda      -> /dev/sda1       (sd*/vd*/hd* end in a letter)
        /dev/loop0    -> /dev/loop0p1    (ends in a digit)
        /dev/nvme0n1  -> /dev/nvme0n1p1
        /dev/mmcblk0  -> /dev/mmcblk0p1

    The old code appended 'p1' unconditionally, producing bogus paths like
    /dev/sdap1 for real SCSI/SATA/virtio disks.
    """
    dev = device.rstrip('/')
    sep = 'p' if dev[-1:].isdigit() else ''
    return f"{dev}{sep}{number}"


def get_loop_devices():
    """
    Get list of loop devices created for LVM practice.

    Returns:
        list: List of loop device paths
    """
    import subprocess
    import os

    loop_dir = '/var/lib/rhcsa-simulator/loops'
    if not os.path.exists(loop_dir):
        return []

    devices = []
    try:
        result = subprocess.run(
            ['losetup', '-a'],
            capture_output=True, text=True, timeout=10
        )
        for line in result.stdout.strip().split('\n'):
            if line and loop_dir in line:
                device = line.split(':')[0]
                devices.append(device)
    except:
        pass

    return devices


def get_swap_practice_device():
    """
    Return the device to use for swap partition practice.
    - Real disk mode: returns the configured real disk (student partitions it with fdisk)
    - Loop mode: returns the loop device backed by disk2.img (3rd practice disk)
    """
    import subprocess
    import os

    # During exam generation, draw a distinct device from the allocator so the
    # swap-partition task doesn't collide with other disk tasks.
    if device_allocation_active():
        return allocate_practice_device()

    cfg = get_practice_device_config()

    if cfg and cfg['mode'] == 'real' and cfg.get('devices'):
        # Real disk — student uses fdisk on it to create a swap partition
        return cfg['devices'][-1]

    # Loop mode: find disk2.img
    disk2_img = '/var/lib/rhcsa-simulator/loops/disk2.img'
    if os.path.exists(disk2_img):
        try:
            result = subprocess.run(
                ['losetup', '-j', disk2_img],
                capture_output=True, text=True, timeout=10
            )
            if result.returncode == 0 and result.stdout.strip():
                return result.stdout.split(':')[0].strip()
        except Exception:
            pass

    # Fallback: last loop device we own
    devices = get_loop_devices()
    if devices:
        return devices[-1]
    return None


def create_practice_devices(count=3, size_mb=500):
    """
    Create loop devices for LVM practice.

    Args:
        count: Number of devices to create (default: 2)
        size_mb: Size of each device in MB (default: 500)

    Returns:
        list: List of created loop device paths
    """
    import subprocess
    import os

    loop_dir = '/var/lib/rhcsa-simulator/loops'
    os.makedirs(loop_dir, exist_ok=True)

    created_devices = []

    for i in range(count):
        img_file = f'{loop_dir}/disk{i}.img'

        # Create sparse file
        try:
            # Remove if exists
            if os.path.exists(img_file):
                # Check if already attached
                result = subprocess.run(
                    ['losetup', '-j', img_file],
                    capture_output=True, text=True, timeout=5
                )
                if result.stdout.strip():
                    # Already attached, get the device
                    device = result.stdout.split(':')[0]
                    created_devices.append(device)
                    continue

            # Create new sparse file
            subprocess.run(
                ['dd', 'if=/dev/zero', f'of={img_file}', 'bs=1M', f'count={size_mb}'],
                capture_output=True, timeout=60
            )

            # Attach to loop device
            result = subprocess.run(
                ['losetup', '-f', '--show', img_file],
                capture_output=True, text=True, timeout=10
            )

            if result.returncode == 0:
                device = result.stdout.strip()
                created_devices.append(device)
        except Exception as e:
            print(f"Error creating practice device: {e}")

    return created_devices


def cleanup_practice_devices():
    """
    Clean up practice devices based on the saved configuration.
    - Loop mode: deactivate swap, remove LVM, detach loops, delete images.
    - Real disk mode: remove LVM structures from configured disks (does NOT
      wipe partition tables — user's data, user's responsibility).
    Also removes the practice device config file.
    """
    import subprocess
    import os

    loop_dir = '/var/lib/rhcsa-simulator/loops'
    cfg = get_practice_device_config()

    try:
        if cfg and cfg['mode'] == 'real':
            # Wipe all practice disks completely (partition table + data)
            for device in cfg.get('devices', []):
                wipe_disk(device)
        else:
            # Loop mode cleanup
            devices = get_loop_devices()
            swap_dev = get_swap_practice_device()
            if swap_dev and swap_dev not in devices:
                devices.append(swap_dev)

            for device in devices:
                # Unmount and deactivate partitions first, then the whole loop
                part_result = subprocess.run(
                    ['lsblk', '-rno', 'NAME,MOUNTPOINT', device],
                    capture_output=True, text=True, timeout=10
                )
                for line in part_result.stdout.splitlines():
                    parts = line.split()
                    name = parts[0]
                    mnt = parts[1] if len(parts) > 1 else ''
                    part_dev = f'/dev/{name}'
                    if part_dev == device:
                        continue
                    subprocess.run(['swapoff', part_dev], capture_output=True, timeout=10)
                    if mnt.startswith('/'):
                        subprocess.run(['umount', '-f', part_dev], capture_output=True, timeout=10)
                subprocess.run(['swapoff', device], capture_output=True, timeout=10)
                # Deactivate any VGs on this loop device before pvremove
                all_devs = [f'/dev/{ln.split()[0]}' for ln in part_result.stdout.splitlines() if ln.split()]
                vg_res = subprocess.run(
                    ['pvs', '--noheadings', '-o', 'vg_name'] + all_devs,
                    capture_output=True, text=True, timeout=10
                )
                for vg in {v.strip() for v in vg_res.stdout.splitlines() if v.strip()}:
                    subprocess.run(['vgchange', '-an', vg], capture_output=True, timeout=10)
                    subprocess.run(['vgremove', '-ff', '-y', vg], capture_output=True, timeout=10)
                for line in part_result.stdout.splitlines():
                    p = line.split()
                    if p:
                        subprocess.run(['pvremove', '-ff', '-y', f'/dev/{p[0]}'],
                                       capture_output=True, timeout=10)
                subprocess.run(['pvremove', '-ff', '-y', device],
                               capture_output=True, timeout=10)
                subprocess.run(['losetup', '-d', device],
                               capture_output=True, timeout=10)

            if os.path.exists(loop_dir):
                for f in os.listdir(loop_dir):
                    if f.endswith('.img'):
                        os.remove(os.path.join(loop_dir, f))

        # Remove config so next run starts fresh
        if os.path.exists(PRACTICE_DEVICE_CONFIG):
            os.remove(PRACTICE_DEVICE_CONFIG)

        return True
    except Exception as e:
        print(f"Error cleaning up: {e}")
        return False


# Static fallback names only. The authoritative answer to "is this the box's
# own VG?" is utils.system_id.is_system_vg(), which probes the live mounts —
# a name list silently mis-classified AlmaLinux's 'almalinux' VG as practice
# storage for as long as nobody had added that name to it.
from utils.system_id import KNOWN_SYSTEM_VG_NAMES as _SYSTEM_VGS
from utils.system_id import is_system_vg

# Bypass the LVM devices file so we can see/remove VGs on loop devices even when
# their devices-file entries are missing or stale (the usual state after an
# interrupted session). Passed via --config to every LVM command in teardown.
_LVM_NODEVFILE = ['--config', 'devices{use_devicesfile=0}']


def _remove_stray_practice_vgs():
    """Deactivate and remove leftover non-system practice VGs (e.g. vg_prac*,
    vg_exam*) from interrupted sessions. These hold loop devices open via
    device-mapper and must go before the loops can be detached. Best-effort."""
    import subprocess

    def run(cmd):
        try:
            subprocess.run(cmd, capture_output=True, timeout=20)
        except Exception:
            pass

    # Stray LVs left mounted (e.g. /mnt/lvm23) or active as swap from an
    # interrupted task keep the mapping open, so deactivate/remove fails. Unmount
    # and swapoff every generated mapper device (vg_exam*/vg_prac*) first.
    try:
        res = subprocess.run(['dmsetup', 'ls'], capture_output=True, text=True, timeout=10)
        for line in res.stdout.splitlines():
            name = line.split()[0] if line.split() else ''
            if name.startswith('vg_') and not name.startswith(tuple(_SYSTEM_VGS)):
                dev = f'/dev/mapper/{name}'
                run(['umount', '-f', dev])
                run(['swapoff', dev])
    except Exception:
        pass

    try:
        res = subprocess.run(
            ['vgs', '--noheadings', '-o', 'vg_name'] + _LVM_NODEVFILE,
            capture_output=True, text=True, timeout=20
        )
        vgs = {v.strip() for v in res.stdout.splitlines() if v.strip()}
    except Exception:
        vgs = set()

    for vg in vgs:
        if is_system_vg(vg):
            continue
        run(['vgchange', '-an', vg] + _LVM_NODEVFILE)
        run(['vgremove', '-ff', '-y', vg] + _LVM_NODEVFILE)

    # Fallback: vgremove can't read metadata off a deleted/zeroed backing image,
    # so any still-active device-mapper LV from a generated VG (vg_exam*/vg_prac*)
    # would keep its loop open. Force-remove those mappings directly.
    try:
        res = subprocess.run(['dmsetup', 'ls'], capture_output=True, text=True, timeout=10)
        for line in res.stdout.splitlines():
            name = line.split()[0] if line.split() else ''
            if name.startswith('vg_') and not name.startswith(tuple(_SYSTEM_VGS)):
                run(['dmsetup', 'remove', '-f', name])
    except Exception:
        pass


def _purge_loop_device(device):
    """Completely tear down a single loop device backed by the loops dir:
    deactivate/remove any LVM on it, wipe filesystem/PV signatures, drop its
    entry from the LVM devices file, and detach it. Best-effort throughout."""
    import subprocess

    def run(cmd):
        try:
            subprocess.run(cmd, capture_output=True, timeout=15)
        except Exception:
            pass

    # Enumerate the whole device plus any child partitions/holders.
    members = [device]
    try:
        res = subprocess.run(['lsblk', '-rno', 'NAME,MOUNTPOINT', device],
                             capture_output=True, text=True, timeout=10)
        for line in res.stdout.splitlines():
            parts = line.split()
            if not parts:
                continue
            dev = f'/dev/{parts[0]}'
            mnt = parts[1] if len(parts) > 1 else ''
            if dev != device:
                members.append(dev)
            if mnt.startswith('/'):
                run(['umount', '-f', dev])
            run(['swapoff', dev])
    except Exception:
        pass

    # Remove any VGs that still live on these members before wiping PV
    # signatures (devices-file check bypassed so loop PVs are visible).
    try:
        vg_res = subprocess.run(['pvs', '--noheadings', '-o', 'vg_name'] + members + _LVM_NODEVFILE,
                                capture_output=True, text=True, timeout=10)
        for vg in {v.strip() for v in vg_res.stdout.splitlines() if v.strip()}:
            if is_system_vg(vg):
                continue
            run(['vgchange', '-an', vg] + _LVM_NODEVFILE)
            run(['vgremove', '-ff', '-y', vg] + _LVM_NODEVFILE)
    except Exception:
        pass

    for dev in members:
        run(['pvremove', '-ff', '-y', dev] + _LVM_NODEVFILE)
        run(['wipefs', '-a', dev])
        # Drop the device from the LVM devices file so a fresh pvcreate doesn't
        # hit "has no PVID (devices file ...)" against stale metadata.
        run(['lvmdevices', '--deldev', dev])

    # Tear down any leftover partition mappings, then detach the loop itself.
    run(['partx', '-d', device])
    run(['losetup', '-d', device])


def reset_practice_loops(count=3, size_mb=500):
    """Guarantee a clean loop-device pool for a new session.

    Interrupted sessions leave orphan loop devices behind — loops still attached
    to '(deleted)' backing images, leftover partitions, stale PV/filesystem
    signatures, and dangling LVM-devices-file entries. Those get handed to disk
    tasks and break pvcreate/mkfs ("device has a signature", "has no PVID").

    This tears down EVERY simulator loop device (including orphans) and recreates
    exactly `count` freshly-zeroed, signature-free images. Returns the new list.
    """
    import subprocess

    loop_dir = '/var/lib/rhcsa-simulator/loops'

    # 0. Remove stray practice VGs first — active LVs from interrupted sessions
    #    hold the loops open via device-mapper and block detach.
    _remove_stray_practice_vgs()

    # 1. Purge all loops backed by our loops dir, including '(deleted)' orphans.
    for device in get_loop_devices():
        _purge_loop_device(device)

    # 2. Delete every backing image so nothing stale is reattached.
    try:
        if os.path.exists(loop_dir):
            for f in os.listdir(loop_dir):
                if f.endswith('.img'):
                    try:
                        os.remove(os.path.join(loop_dir, f))
                    except Exception:
                        pass
    except Exception:
        pass

    # 3. Strip any leftover loop_file entries from the LVM devices file so fresh
    #    loops are treated as new devices and auto-registered by pvcreate.
    devices_file = '/etc/lvm/devices/system.devices'
    try:
        if os.path.exists(devices_file):
            with open(devices_file) as fh:
                lines = fh.readlines()
            kept = [ln for ln in lines
                    if not ('IDTYPE=loop_file' in ln and loop_dir in ln)]
            if len(kept) != len(lines):
                with open(devices_file, 'w') as fh:
                    fh.writelines(kept)
    except Exception:
        pass

    # 4. Recreate a clean pool and wipe each fresh device for good measure.
    created = create_practice_devices(count=count, size_mb=size_mb)
    for dev in created:
        try:
            subprocess.run(['wipefs', '-a', dev], capture_output=True, timeout=10)
        except Exception:
            pass
    if created:
        save_practice_device_config('loop', get_loop_devices())
    return get_loop_devices()


def get_practice_device():
    """
    Get a device suitable for LVM practice.
    Uses DeviceManager for smart detection (handles system disks, caching,
    and disks with existing practice LVM), then falls back to loop devices.

    Returns:
        str: Device path or None if none available
    """
    # During exam generation an allocator hands out a *distinct* device per
    # consuming task so two disk tasks never collide on the same disk.
    if device_allocation_active():
        return allocate_practice_device()

    # Use DeviceManager for smart detection (skips system disks, caches result,
    # recognizes disks with existing practice PVs/VGs)
    # Check saved config first
    cfg = get_practice_device_config()
    if cfg and cfg.get('devices'):
        if cfg['mode'] == 'loop':
            # Re-attach loop devices if needed
            loop_devices = get_loop_devices()
            if loop_devices:
                return loop_devices[0]
            # Images may still exist but not attached — recreate
            created = create_practice_devices(count=3, size_mb=500)
            if created:
                return created[0]
        else:
            # Real disk mode — return first configured device
            return cfg['devices'][0]

    # No config: fall back to loop devices if any exist
    loop_devices = get_loop_devices()
    if loop_devices:
        return loop_devices[0]

    return None


# ---------------------------------------------------------------------------
# Exam device pool + allocator
#
# Several task categories (LVM, partitioning, filesystems, swap) each need a
# whole disk. Historically they all called get_practice_device() and got the
# *same* first device, so an LVM task and a partition task in the same exam
# would fight over one disk. The allocator below hands each consuming task a
# distinct device drawn from a pool of >= `min_loops` loop devices (auto-created
# if missing) plus any spare non-system real disk (e.g. /dev/sda).
# ---------------------------------------------------------------------------

_device_alloc_pool = None   # list while allocation is active, else None
_device_alloc_idx = 0


def ensure_loop_devices(minimum=3):
    """Ensure at least `minimum` loop practice devices exist; create if needed."""
    loops = get_loop_devices()
    if len(loops) < minimum:
        create_practice_devices(count=minimum, size_mb=500)
        loops = get_loop_devices()
        if loops:
            save_practice_device_config('loop', loops)
    return get_loop_devices()


def loop_device_capacity(size_mb=500, reserve_mb=1024):
    """How many practice loop devices CAN exist: those already attached plus
    as many more as free space under the loops directory allows (keeping
    reserve_mb free). Loop images are created on demand at exam provisioning
    (ensure_loop_devices), so selection budgets should use this rather than
    the count currently attached."""
    existing = len(get_loop_devices())
    try:
        base = '/var/lib/rhcsa-simulator'
        os.makedirs(base, exist_ok=True)
        st = os.statvfs(base)
        free_mb = st.f_bavail * st.f_frsize // (1024 * 1024)
    except Exception:
        return max(existing, 3)
    return existing + max(0, int((free_mb - reserve_mb) // size_mb))


def get_spare_real_disks():
    """Non-system, unmounted real disks (e.g. /dev/sda) usable for practice."""
    spares = []
    try:
        for d in list_all_block_devices():
            if not d.get('is_system') and not d.get('mounted'):
                spares.append(d['device'])
    except Exception:
        pass
    return spares


def build_device_pool(min_loops=3):
    """Ordered list of distinct practice devices: loop devices (>= min_loops)
    first, then spare non-system real disks (e.g. /dev/sda)."""
    pool = list(ensure_loop_devices(min_loops))
    for dev in get_spare_real_disks():
        if dev not in pool:
            pool.append(dev)
    return pool


def begin_device_allocation(min_loops=3):
    """Start handing out distinct devices (call once at exam generation)."""
    global _device_alloc_pool, _device_alloc_idx
    _device_alloc_pool = build_device_pool(min_loops)
    _device_alloc_idx = 0
    return list(_device_alloc_pool)


def end_device_allocation():
    """Stop the allocator; get_practice_device() reverts to normal behaviour."""
    global _device_alloc_pool, _device_alloc_idx
    _device_alloc_pool = None
    _device_alloc_idx = 0


def device_allocation_active():
    return _device_alloc_pool is not None


def allocate_practice_device():
    """Return the next un-allocated device, or None if the pool is exhausted."""
    global _device_alloc_idx
    if _device_alloc_pool is None:
        return None
    if _device_alloc_idx < len(_device_alloc_pool):
        dev = _device_alloc_pool[_device_alloc_idx]
        _device_alloc_idx += 1
        return dev
    return None


def get_all_practice_devices():
    """
    Get all devices configured for LVM/partition practice.
    Respects the saved practice device config.
    """
    cfg = get_practice_device_config()
    if cfg and cfg.get('devices'):
        if cfg['mode'] == 'loop':
            return get_loop_devices()
        else:
            return cfg['devices']

    # No config — return whatever loop devices are attached
    return get_loop_devices()


def get_practice_lv():
    """
    Get an existing non-system LV suitable for practice (extend tasks).
    Returns tuple of (vg_name, lv_name) or (None, None) if none found.
    """
    import subprocess
    
    try:
        result = subprocess.run(
            ['lvs', '--noheadings', '-o', 'vg_name,lv_name'],
            capture_output=True, text=True, timeout=10
        )
        
        if result.returncode != 0:
            return None, None

        from utils.system_id import is_system_vg

        for line in result.stdout.strip().splitlines():
            parts = line.split()
            if len(parts) >= 2:
                vg_name = parts[0]
                lv_name = parts[1]
                # Never hand back an LV that belongs to the OS itself.
                if not is_system_vg(vg_name):
                    return vg_name, lv_name
        
        return None, None
    except Exception:
        return None, None


def get_practice_vg():
    """
    Get an existing non-system VG suitable for practice.
    Returns vg_name or None if none found.
    """
    import subprocess
    
    try:
        result = subprocess.run(
            ['vgs', '--noheadings', '-o', 'vg_name,vg_free'],
            capture_output=True, text=True, timeout=10
        )
        
        if result.returncode != 0:
            return None

        from utils.system_id import is_system_vg

        for line in result.stdout.strip().splitlines():
            parts = line.split()
            if len(parts) >= 1:
                vg_name = parts[0]
                # Never hand back the VG that backs the OS itself.
                if not is_system_vg(vg_name):
                    return vg_name

        return None
    except Exception:
        return None


def populate_dnf_history(target_transactions=12, progress_callback=None):
    """
    Build up DNF transaction history by installing and removing lightweight
    packages in cycles. Only installs packages not currently present so it
    never removes something the user already had.

    Returns the number of install/remove cycles completed.
    """
    import subprocess
    import logging

    logger = logging.getLogger(__name__)

    # Small packages available in RHEL 10 BaseOS/AppStream
    candidates = [
        'tree', 'dos2unix', 'bc', 'mtr', 'strace',
        'lsof', 'pv', 'words', 'screen', 'nmap',
        'zip', 'ltrace', 'telnet', 'whois', 'jq',
    ]

    cycles = 0

    for pkg in candidates:
        if cycles >= target_transactions:
            break

        # Skip if already installed — never touch pre-existing packages
        check = subprocess.run(['rpm', '-q', pkg], capture_output=True)
        if check.returncode == 0:
            logger.debug(f"Skipping {pkg} (already installed)")
            continue

        if progress_callback:
            progress_callback(f"Installing {pkg}...")

        install = subprocess.run(
            ['dnf', 'install', '-y', '--quiet', pkg],
            capture_output=True, text=True, timeout=120
        )
        if install.returncode != 0:
            logger.debug(f"Could not install {pkg}: {install.stderr[:200]}")
            continue

        if progress_callback:
            progress_callback(f"Removing {pkg}...")

        subprocess.run(
            ['dnf', 'remove', '-y', '--quiet', pkg],
            capture_output=True, text=True, timeout=120
        )
        cycles += 1
        logger.info(f"DNF history cycle: {pkg} installed+removed")

    return cycles
