"""
Disk partitioning tasks for RHCSA EX200 v10 exam.
Covers MBR/GPT partition creation, resizing, deletion,
partition+format combos, and partition table conversion.
"""

import random
import logging
from tasks.base import BaseTask
from tasks.registry import TaskRegistry
from core.validator import ValidationCheck, ValidationResult
from validators.safe_executor import execute_safe


logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _random_device():
    """Return a practice disk device path that actually exists on the system.

    Uses the smart device detection from helpers (DeviceManager -> raw block
    devices -> loop devices -> create loop devices) so that partitioning tasks
    never reference a device the student cannot use.
    """
    try:
        from utils.helpers import get_practice_device
        device = get_practice_device()
        if device:
            return device
    except Exception:
        pass
    # Last-resort fallback so tasks can still display a description
    return '/dev/sdb'


def _partition_dev(device, number):
    """Build partition device path. Inserts a 'p' before the number only when
    the device name ends in a digit (loop0p1, nvme0n1p1, mmcblk0p1) but not for
    sd*/vd*/hd* (sda1). Delegates to the shared helper."""
    from utils.helpers import partition_device
    return partition_device(device, number)


# ===== 1. CreateMBRPartitionTask ==========================================

@TaskRegistry.register("partitioning")
class CreateMBRPartitionTask(BaseTask):
    """Create an MBR (msdos) partition using fdisk or parted.

    v9 only. The RHEL 9 objective reads "List, create, delete partitions on
    MBR and GPT disks"; RHEL 10 narrowed it to "List, create, and delete
    partitions on GPT disks", so this is off-syllabus for v10.
    """

    exam_versions = (9,)

    disk_slots = 1

    def __init__(self):
        super().__init__(
            id="part_mbr_create",
            category="partitioning",
            difficulty="medium",
            points=10,
        )
        self.task_order = 10
        self.tags = ["fdisk", "parted", "mbr", "partition"]
        self.exam_tips = [
            "Use fdisk for MBR disks - it is the traditional tool.",
            "Remember to run 'partprobe' or 'udevadm settle' after writing.",
            "MBR supports at most 4 primary partitions (or 3 primary + 1 extended).",
        ]

    def generate(self, **params):
        self.params["device"] = params.get("device", _random_device())
        self.params["size_mb"] = params.get("size", random.choice([100, 150, 200, 300]))
        self.params["part_num"] = params.get("part_num", random.randint(1, 3))
        self.params["part_type"] = params.get("part_type", "primary")

        dev = self.params["device"]
        size = self.params["size_mb"]
        ptype = self.params["part_type"]
        pnum = self.params["part_num"]

        self.description = (
            f"Using an MBR (msdos) partition table, create a {size} MiB "
            f"{ptype} partition (number {pnum}) on {dev}. The kernel must "
            f"recognise the new partition."
        )

        self.hints = [
            f"Create MBR label (if new disk): parted -s {dev} mklabel msdos",
            f"Using fdisk: fdisk {dev}  ->  n (new), p (primary), w (write)",
            f"Using parted: parted -s {dev} mkpart {ptype} ext4 1MiB {size + 1}MiB",
            "Update kernel partition table: partprobe",
            f"Verify: lsblk {dev}  or  fdisk -l {dev}",
        ]
        return self

    def validate(self):
        checks = []
        total = 0
        dev = self.params["device"]
        pnum = self.params["part_num"]
        size = self.params["size_mb"]

        # Check 1: MBR (msdos) label  (3 pts)
        res = execute_safe(["parted", "-s", dev, "print"])
        if res.success and "msdos" in res.stdout.lower():
            checks.append(ValidationCheck("mbr_label", True, 3, "Disk has MBR (msdos) partition table"))
            total += 3
        else:
            checks.append(ValidationCheck("mbr_label", False, 0, "Disk does not have MBR partition table", max_points=3))

        # Check 2: Partition exists  (4 pts)
        part_dev = _partition_dev(dev, pnum)
        res2 = execute_safe(["lsblk", "-ln", "-o", "NAME,TYPE", dev])
        part_name = part_dev.split("/")[-1]
        if res2.success and part_name in res2.stdout:
            checks.append(ValidationCheck("partition_exists", True, 4, f"Partition {part_dev} exists"))
            total += 4
        else:
            checks.append(ValidationCheck("partition_exists", False, 0, f"Partition {part_dev} not found", max_points=4))

        # Check 3: Approximate size  (3 pts)
        res3 = execute_safe(["lsblk", "-bln", "-o", "NAME,SIZE", dev])
        if res3.success:
            for line in res3.stdout.strip().splitlines():
                parts = line.split()
                if len(parts) >= 2 and part_name in parts[0]:
                    try:
                        actual_mb = int(parts[1]) / (1024 * 1024)
                        tolerance = size * 0.15
                        if abs(actual_mb - size) <= tolerance:
                            checks.append(ValidationCheck("partition_size", True, 3, f"Size ~{int(actual_mb)} MiB (expected {size} MiB)"))
                            total += 3
                        else:
                            checks.append(ValidationCheck("partition_size", False, 0, f"Size {int(actual_mb)} MiB, expected ~{size} MiB", max_points=3))
                    except (ValueError, IndexError):
                        checks.append(ValidationCheck("partition_size", False, 0, "Could not parse partition size", max_points=3))
                    break
            else:
                checks.append(ValidationCheck("partition_size", False, 0, "Partition not found in lsblk output", max_points=3))
        else:
            checks.append(ValidationCheck("partition_size", False, 0, "Could not query block devices", max_points=3))

        passed = total >= (self.points * 0.6)
        return ValidationResult(self.id, passed, total, self.points, checks)


# ===== 2. CreateGPTPartitionTask ==========================================

@TaskRegistry.register("partitioning")
class CreateGPTPartitionTask(BaseTask):
    """Create a GPT partition table and partition using parted or gdisk."""

    disk_slots = 1

    def __init__(self):
        super().__init__(
            id="part_gpt_create",
            category="partitioning",
            difficulty="medium",
            points=10,
        )
        self.task_order = 10
        self.tags = ["gpt", "parted", "gdisk", "partition"]
        self.exam_tips = [
            "GPT is required for disks >2 TiB.",
            "parted is the preferred tool for GPT on RHEL.",
            "GPT supports up to 128 partitions by default.",
        ]

    def generate(self, **params):
        self.params["device"] = params.get("device", _random_device())
        self.params["size_mb"] = params.get("size", random.choice([100, 150, 200, 300]))
        self.params["part_name"] = params.get("name", random.choice(["data", "apps", "backup", "logs"]))

        dev = self.params["device"]
        size = self.params["size_mb"]
        name = self.params["part_name"]

        self.description = (
            f"Create a GPT partition table on {dev} with one {size} MiB "
            f"partition named '{name}'."
        )

        self.hints = [
            f"Create GPT label: parted -s {dev} mklabel gpt",
            f"Create partition: parted -s {dev} mkpart {name} ext4 1MiB {size + 1}MiB",
            f"Verify: parted -s {dev} print",
            "GPT partitions can have human-readable names.",
        ]
        return self

    def validate(self):
        checks = []
        total = 0
        dev = self.params["device"]

        # Check 1: GPT label  (4 pts)
        res = execute_safe(["parted", "-s", dev, "print"])
        if res.success and "gpt" in res.stdout.lower():
            checks.append(ValidationCheck("gpt_label", True, 4, "GPT partition table exists"))
            total += 4
        else:
            msg = "MBR found instead of GPT" if (res.success and "msdos" in res.stdout.lower()) else "No GPT partition table found"
            checks.append(ValidationCheck("gpt_label", False, 0, msg, max_points=4))

        # Check 2: Partition exists  (3 pts)
        res2 = execute_safe(["lsblk", "-ln", "-o", "NAME,TYPE", dev])
        if res2.success and "part" in res2.stdout:
            checks.append(ValidationCheck("partition_exists", True, 3, "Partition exists on GPT disk"))
            total += 3
        else:
            checks.append(ValidationCheck("partition_exists", False, 0, "No partitions found", max_points=3))

        # Check 3: Approximate size  (3 pts)
        part_dev = _partition_dev(dev, 1)
        part_name = part_dev.split("/")[-1]
        res3 = execute_safe(["lsblk", "-bln", "-o", "NAME,SIZE", dev])
        size = self.params["size_mb"]
        if res3.success:
            for line in res3.stdout.strip().splitlines():
                cols = line.split()
                if len(cols) >= 2 and part_name in cols[0]:
                    try:
                        actual_mb = int(cols[1]) / (1024 * 1024)
                        if abs(actual_mb - size) <= size * 0.15:
                            checks.append(ValidationCheck("partition_size", True, 3, f"Size ~{int(actual_mb)} MiB"))
                            total += 3
                        else:
                            checks.append(ValidationCheck("partition_size", False, 0, f"Size {int(actual_mb)} MiB, expected ~{size} MiB", max_points=3))
                    except (ValueError, IndexError):
                        checks.append(ValidationCheck("partition_size", False, 0, "Could not parse size", max_points=3))
                    break
            else:
                checks.append(ValidationCheck("partition_size", False, 0, "Partition not in lsblk", max_points=3))
        else:
            checks.append(ValidationCheck("partition_size", False, 0, "lsblk failed", max_points=3))

        passed = total >= (self.points * 0.6)
        return ValidationResult(self.id, passed, total, self.points, checks)


# ===== 3. ResizePartitionTask =============================================

@TaskRegistry.register("partitioning")
class ResizePartitionTask(BaseTask):
    """Resize an existing partition (grow) using parted or growpart."""

    disk_slots = 1

    def __init__(self):
        super().__init__(
            id="part_resize",
            category="partitioning",
            difficulty="hard",
            points=15,
        )
        self.task_order = 30
        self.tags = ["parted", "growpart", "resize", "partition"]
        self.exam_tips = [
            "You can only grow a partition non-destructively; shrinking risks data loss.",
            "After resizing, also resize the filesystem (xfs_growfs / resize2fs).",
            "parted resizepart or growpart are the common tools.",
        ]

    def generate(self, **params):
        self.params["device"] = params.get("device", _random_device())
        self.params["part_num"] = params.get("part_num", 1)
        self.params["new_size_mb"] = params.get("new_size", random.choice([300, 350, 400]))

        dev = self.params["device"]
        pnum = self.params["part_num"]
        new_size = self.params["new_size_mb"]
        part_dev = _partition_dev(dev, pnum)

        self.description = (
            f"Grow partition {pnum} on {dev} to {new_size} MiB and resize its "
            f"filesystem (xfs or ext4) to match, without data loss."
        )

        self.hints = [
            f"Using parted: parted -s {dev} resizepart {pnum} {new_size}MiB",
            f"Using growpart: growpart {dev} {pnum}",
            "For XFS: xfs_growfs <mount_point>",
            f"For ext4: resize2fs {part_dev}",
            "Always resize filesystem AFTER growing the partition.",
        ]
        return self

    def validate(self):
        checks = []
        total = 0
        dev = self.params["device"]
        pnum = self.params["part_num"]
        new_size = self.params["new_size_mb"]
        part_dev = _partition_dev(dev, pnum)
        part_name = part_dev.split("/")[-1]

        # Check 1: Partition exists  (5 pts)
        res = execute_safe(["lsblk", "-ln", "-o", "NAME,TYPE", dev])
        if res.success and part_name in res.stdout:
            checks.append(ValidationCheck("partition_exists", True, 5, f"Partition {part_dev} exists"))
            total += 5
        else:
            checks.append(ValidationCheck("partition_exists", False, 0, f"Partition {part_dev} not found", max_points=5))
            return ValidationResult(self.id, False, total, self.points, checks)

        # Check 2: Partition size meets target  (6 pts)
        res2 = execute_safe(["lsblk", "-bln", "-o", "NAME,SIZE", dev])
        if res2.success:
            for line in res2.stdout.strip().splitlines():
                cols = line.split()
                if len(cols) >= 2 and part_name in cols[0]:
                    try:
                        actual_mb = int(cols[1]) / (1024 * 1024)
                        tolerance = new_size * 0.10
                        if actual_mb >= new_size - tolerance:
                            checks.append(ValidationCheck("partition_resized", True, 6, f"Partition is ~{int(actual_mb)} MiB (target {new_size} MiB)"))
                            total += 6
                        else:
                            checks.append(ValidationCheck("partition_resized", False, 0, f"Partition is {int(actual_mb)} MiB, expected >= ~{new_size} MiB", max_points=6))
                    except (ValueError, IndexError):
                        checks.append(ValidationCheck("partition_resized", False, 0, "Could not parse size", max_points=6))
                    break
        else:
            checks.append(ValidationCheck("partition_resized", False, 0, "Could not query size", max_points=6))

        # Check 3: Filesystem still intact  (4 pts)
        res3 = execute_safe(["blkid", "-o", "value", "-s", "TYPE", part_dev])
        if res3.success and res3.stdout.strip():
            checks.append(ValidationCheck("fs_intact", True, 4, f"Filesystem ({res3.stdout.strip()}) intact on partition"))
            total += 4
        else:
            checks.append(ValidationCheck("fs_intact", False, 0, "No filesystem detected on partition", max_points=4))

        passed = total >= (self.points * 0.6)
        return ValidationResult(self.id, passed, total, self.points, checks)


# ===== 4. DeletePartitionTask =============================================

@TaskRegistry.register("partitioning")
class DeletePartitionTask(BaseTask):
    """Delete an existing partition."""

    disk_slots = 1

    def __init__(self):
        super().__init__(
            id="part_delete",
            category="partitioning",
            difficulty="easy",
            points=6,
        )
        self.task_order = 40
        self.tags = ["fdisk", "parted", "delete", "partition"]
        self.exam_tips = [
            "Always unmount and remove fstab entries before deleting a partition.",
            "Use wipefs -a to clean partition signatures if needed.",
        ]

    def generate(self, **params):
        self.params["device"] = params.get("device", _random_device())
        self.params["part_num"] = params.get("part_num", random.choice([1, 2, 3]))

        dev = self.params["device"]
        pnum = self.params["part_num"]
        part_dev = _partition_dev(dev, pnum)

        self.description = (
            f"Completely remove partition {pnum} on {dev}, including any "
            f"mount and /etc/fstab entry for {part_dev}. The kernel must "
            f"recognise the change."
        )

        self.hints = [
            f"Unmount: umount {part_dev}",
            f"Using fdisk: fdisk {dev}  ->  d (delete), w (write)",
            f"Using parted: parted -s {dev} rm {pnum}",
            "Update kernel: partprobe",
            f"Verify: lsblk {dev}",
        ]
        return self

    def validate(self):
        checks = []
        total = 0
        dev = self.params["device"]
        pnum = self.params["part_num"]
        part_dev = _partition_dev(dev, pnum)
        part_name = part_dev.split("/")[-1]

        # Check 1: Partition should NOT exist  (4 pts)
        res = execute_safe(["lsblk", "-ln", "-o", "NAME", dev])
        if res.success and part_name not in res.stdout:
            checks.append(ValidationCheck("partition_deleted", True, 4, f"Partition {pnum} deleted successfully"))
            total += 4
        else:
            checks.append(ValidationCheck("partition_deleted", False, 0, f"Partition {pnum} still exists", max_points=4))

        # Check 2: Not mounted  (2 pts)
        res2 = execute_safe(["findmnt", "-rn", "-o", "SOURCE", part_dev])
        if not res2.success or not res2.stdout.strip():
            checks.append(ValidationCheck("not_mounted", True, 2, f"{part_dev} is not mounted"))
            total += 2
        else:
            checks.append(ValidationCheck("not_mounted", False, 0, f"{part_dev} is still mounted", max_points=2))

        passed = total >= (self.points * 0.6)
        return ValidationResult(self.id, passed, total, self.points, checks)


# ===== 5. PartitionAndFormatTask ==========================================

@TaskRegistry.register("partitioning")
class PartitionAndFormatTask(BaseTask):
    """Create a partition, format it, mount it, and add to fstab (exam-style)."""

    disk_slots = 1

    def __init__(self):
        super().__init__(
            id="part_format_mount",
            category="partitioning",
            difficulty="exam",
            points=15,
        )
        self.task_order = 20
        self.requires_persistence = True
        self.tags = ["partition", "mkfs", "mount", "fstab", "persistence"]
        self.exam_tips = [
            "On the real exam you MUST use UUID in /etc/fstab.",
            "Always test with 'mount -a' and 'findmnt --verify' before finishing.",
            "A bad fstab entry can prevent the system from booting.",
        ]

    def generate(self, **params):
        self.params["device"] = params.get("device", _random_device())
        self.params["part_num"] = params.get("part_num", 1)
        # Pick fstype first: RHEL 10 mkfs.xfs refuses filesystems <= 300MB, so an
        # XFS partition must be larger than that. Loop practice disks are 500MB,
        # so 350-450MB fits. ext4 has no such floor.
        self.params["fstype"] = params.get("fstype", random.choice(["xfs", "ext4"]))
        if self.params["fstype"] == "xfs":
            self.params["size_mb"] = params.get("size", random.choice([350, 400, 450]))
        else:
            self.params["size_mb"] = params.get("size", random.choice([100, 150, 200, 300]))
        self.params["mount_point"] = params.get("mount_point", f"/mnt/{random.choice(['data', 'apps', 'backup', 'extra'])}{random.randint(1, 99)}")

        dev = self.params["device"]
        pnum = self.params["part_num"]
        size = self.params["size_mb"]
        fs = self.params["fstype"]
        mp = self.params["mount_point"]
        part_dev = _partition_dev(dev, pnum)

        self.description = (
            f"Use {dev} to create a {size} MiB partition (number {pnum}) "
            f"formatted with {fs} and mounted at {mp}, persistently across "
            f"reboots. Identify it by UUID in /etc/fstab."
        )

        self.hints = [
            f"parted -s {dev} mklabel gpt  (if disk is new)",
            f"parted -s {dev} mkpart primary {fs} 1MiB {size + 1}MiB",
            f"mkfs.{fs} {part_dev}",
            f"mkdir -p {mp}",
            f"mount {part_dev} {mp}",
            f"Get UUID: blkid {part_dev}",
            f"fstab entry: UUID=<uuid> {mp} {fs} defaults 0 0",
            "Test: mount -a && findmnt --verify",
        ]
        return self

    def validate(self):
        checks = []
        total = 0
        dev = self.params["device"]
        pnum = self.params["part_num"]
        fs = self.params["fstype"]
        mp = self.params["mount_point"]
        part_dev = _partition_dev(dev, pnum)
        part_name = part_dev.split("/")[-1]

        # Check 1: Partition exists  (3 pts)
        res = execute_safe(["lsblk", "-ln", "-o", "NAME,TYPE", dev])
        if res.success and part_name in res.stdout:
            checks.append(ValidationCheck("partition_exists", True, 3, f"Partition {part_dev} exists"))
            total += 3
        else:
            checks.append(ValidationCheck("partition_exists", False, 0, f"Partition {part_dev} not found", max_points=3))

        # Check 2: Filesystem type  (3 pts)
        res2 = execute_safe(["blkid", "-o", "value", "-s", "TYPE", part_dev])
        if res2.success and res2.stdout.strip() == fs:
            checks.append(ValidationCheck("fs_type", True, 3, f"Filesystem is {fs}"))
            total += 3
        else:
            actual = res2.stdout.strip() if res2.success else "unknown"
            checks.append(ValidationCheck("fs_type", False, 0, f"Filesystem is '{actual}', expected '{fs}'", max_points=3))

        # Check 3: Mounted at correct point  (3 pts)
        res3 = execute_safe(["findmnt", "-rn", "-o", "TARGET", part_dev])
        if res3.success and mp in res3.stdout:
            checks.append(ValidationCheck("mounted", True, 3, f"Mounted at {mp}"))
            total += 3
        else:
            checks.append(ValidationCheck("mounted", False, 0, f"Not mounted at {mp}", max_points=3))

        # Check 4: fstab entry with UUID  (4 pts)
        res4 = execute_safe(["blkid", "-o", "value", "-s", "UUID", part_dev])
        uuid = res4.stdout.strip() if res4.success else ""
        fstab_ok = False
        fstab_uuid = False
        try:
            with open("/etc/fstab", "r") as f:
                for line in f:
                    stripped = line.strip()
                    if stripped.startswith("#") or not stripped:
                        continue
                    if mp in stripped:
                        fstab_ok = True
                        if uuid and uuid in stripped:
                            fstab_uuid = True
                        break
        except Exception:
            pass

        if fstab_uuid:
            checks.append(ValidationCheck("fstab_uuid", True, 4, "fstab entry present with UUID"))
            total += 4
        elif fstab_ok:
            checks.append(ValidationCheck("fstab_uuid", True, 2, "fstab entry present but NOT using UUID (partial credit)"))
            total += 2
        else:
            checks.append(ValidationCheck("fstab_uuid", False, 0, "No fstab entry found", max_points=4))

        # Check 5: mount point directory exists  (2 pts)
        import os
        if os.path.isdir(mp):
            checks.append(ValidationCheck("mount_dir", True, 2, f"Mount point {mp} exists"))
            total += 2
        else:
            checks.append(ValidationCheck("mount_dir", False, 0, f"Mount point {mp} missing", max_points=2))

        passed = total >= (self.points * 0.6)
        return ValidationResult(self.id, passed, total, self.points, checks)
