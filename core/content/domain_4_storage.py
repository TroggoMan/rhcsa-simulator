"""
Domain 4: Storage & Filesystems
Categories: partitioning, lvm, filesystems, swap (NEW), network_storage
"""

CONTENT = {
    "partitioning": {
        "name": "Disk Partitioning (fdisk/parted)",
        "explanation": """
Disk partitioning creates separate regions on storage devices. RHEL supports
MBR (Master Boot Record) and GPT (GUID Partition Table) schemes.

MBR vs GPT:
  MBR (msdos):
    - Up to 4 primary partitions (or 3 primary + 1 extended)
    - Maximum disk size: 2TB
    - Legacy BIOS boot

  GPT (GUID):
    - Up to 128 partitions
    - Maximum disk size: 9.4 ZB (practically unlimited)
    - Required for UEFI boot
    - Includes backup partition table

PARTITION TYPES:
  Linux filesystem (83/8300): Standard Linux partitions
  Linux LVM (8e/8e00): For LVM physical volumes
  Linux swap (82/8200): Swap partitions
  EFI System (ef00): EFI boot partitions

TOOLS:
  fdisk: Interactive MBR/GPT partitioning
  parted: Scriptable MBR/GPT partitioning
  gdisk: GPT-specific tool
  partprobe: Update kernel partition table
        """,
        "commands": [
            {
                "name": "View Partition Table",
                "syntax": "fdisk -l <device> / parted <device> print",
                "example": "fdisk -l /dev/sdb\nparted /dev/sdb print",
                "flags": {
                    "fdisk -l": "List partitions (all or specific disk)",
                    "parted print": "Show partition table",
                    "lsblk": "Tree view of block devices",
                },
            },
            {
                "name": "Create Partition (fdisk)",
                "syntax": "fdisk <device>",
                "example": "fdisk /dev/sdb\n  n (new)\n  p (primary)\n  1 (number)\n  <enter> (default start)\n  +500M (size)\n  w (write)",
                "flags": {
                    "n": "New partition",
                    "p": "Primary partition",
                    "e": "Extended partition",
                    "t": "Change partition type",
                    "d": "Delete partition",
                    "w": "Write changes and exit",
                    "q": "Quit without saving",
                },
            },
            {
                "name": "Create Partition (parted)",
                "syntax": "parted <device> mkpart <type> <fstype> <start> <end>",
                "example": "parted /dev/sdb mkpart primary ext4 0% 500MiB",
                "flags": {
                    "mklabel gpt/msdos": "Create partition table",
                    "mkpart": "Create partition",
                    "rm N": "Remove partition N",
                    "print": "Show partitions",
                    "set N lvm on": "Set LVM flag",
                },
            },
            {
                "name": "Create GPT Label",
                "syntax": "parted <device> mklabel gpt",
                "example": "parted /dev/sdb mklabel gpt\nparted /dev/sdb mkpart data ext4 0% 100%",
                "flags": {
                    "mklabel gpt": "Create GPT partition table",
                    "mklabel msdos": "Create MBR partition table",
                    "WARNING": "Destroys all existing partitions!",
                },
            },
            {
                "name": "Set LVM Type",
                "syntax": "fdisk: t, 8e / parted: set N lvm on",
                "example": "parted /dev/sdb set 1 lvm on",
                "flags": {
                    "fdisk t, 8e": "Set type to Linux LVM",
                    "parted set N lvm on": "Enable LVM flag",
                    "Required for": "LVM physical volumes",
                },
            },
            {
                "name": "Update Kernel",
                "syntax": "partprobe <device>",
                "example": "partprobe /dev/sdb",
                "flags": {
                    "partprobe": "Inform kernel of partition changes",
                    "Without device": "Scans all disks",
                    "Required after": "Creating/deleting partitions",
                },
            },
        ],
        "common_mistakes": [
            "Forgetting to run partprobe after changes",
            "Wrong partition type for LVM (must be 8e)",
            "Creating MBR when GPT is needed (>2TB disk)",
            "Forgetting to write changes in fdisk (w command)",
            "Partition table type mismatch with boot mode (UEFI needs GPT)",
        ],
        "exam_tricks": [
            "parted is scriptable: parted -s /dev/sdb mkpart ...",
            "For LVM: create partition, set type to 8e, then pvcreate",
            "partprobe updates kernel without reboot",
            "GPT allows more partitions and larger disks",
            "Check with lsblk after partitioning",
            "Not every task states a size. 'Create a backup partition on "
            "/dev/sda' with no number is a real exam phrasing — it means the "
            "size is yours to choose, not that you missed a line. Pick "
            "something sensible, leave room for later tasks on the same disk, "
            "and move on.",
            "When a size IS given, treat it as exact and check the tolerance: "
            "'1GiB' is 1024MiB, not 1000MiB. Mixing the two is a common "
            "silent failure.",
        ],
    },
    "lvm": {
        "name": "LVM (Logical Volume Management)",
        "explanation": """
LVM provides flexible disk management with physical volumes (PV),
volume groups (VG), and logical volumes (LV). The hierarchy is:
Disk -> PV -> VG -> LV -> Filesystem. You must know creation, extension,
and reduction operations. The exam tests your ability to create the
full LVM stack and resize volumes.
        """,
        "commands": [
            {
                "name": "Create Physical Volume",
                "syntax": "pvcreate <device>",
                "example": "pvcreate /dev/sdb",
                "flags": {
                    "/dev/sdX": "Block device to use",
                    "pvdisplay": "Show PV details",
                    "pvs": "List PVs (short)",
                },
            },
            {
                "name": "Create Volume Group",
                "syntax": "vgcreate <vgname> <pv>",
                "example": "vgcreate vgdata /dev/sdb",
                "flags": {
                    "vgname": "Name for volume group",
                    "pv": "Physical volume(s) to include",
                    "vgdisplay": "Show VG details",
                    "vgs": "List VGs (short)",
                },
            },
            {
                "name": "Create Logical Volume",
                "syntax": "lvcreate -n <lvname> -L <size> <vgname>",
                "example": "lvcreate -n lvdata -L 500M vgdata",
                "flags": {
                    "-n": "Logical volume name",
                    "-L": "Size (M, G, T)",
                    "-l": "Size in extents (e.g., -l 100%FREE)",
                    "lvdisplay": "Show LV details",
                    "lvs": "List LVs (short)",
                },
            },
            {
                "name": "Extend Logical Volume",
                "syntax": "lvextend -L +<size> <lv_path> && resize2fs/xfs_growfs",
                "example": "lvextend -L +1G /dev/vgdata/lvdata\nxfs_growfs /dev/vgdata/lvdata",
                "flags": {
                    "-L +size": "Increase by size",
                    "-L size": "Set to absolute size",
                    "-r": "Resize filesystem automatically",
                    "resize2fs": "For ext4 filesystems",
                    "xfs_growfs": "For XFS filesystems",
                },
            },
        ],
        "common_mistakes": [
            "Wrong order: must create PV -> VG -> LV",
            "Forgetting to resize filesystem after extending LV",
            "Using wrong filesystem resize command (ext4 vs XFS)",
            "Not using -r flag to auto-resize",
            "Insufficient space in VG for LV",
        ],
        "exam_tricks": [
            "When a size is given, watch the units (M vs MB vs MiB)",
            "But do NOT assume every task gives one. Some are deliberately "
            "open ('create a backup volume in vg01'), leaving the size to "
            "your judgement — that is not a missing detail. Size it to fit "
            "the VG with room for later tasks, then say so and move on.",
            "Sized in extents rather than bytes? -l takes extents, -L takes "
            "bytes: lvcreate -l 128 (extents) vs lvcreate -L 512M. "
            "-l 100%FREE takes whatever is left, which is often the right "
            "answer for an open-ended 'use the remaining space' task.",
            "May ask to extend existing LV (not create new)",
            "Filesystem resize is separate step (unless -r flag)",
            "Path is /dev/vgname/lvname or /dev/mapper/vgname-lvname",
        ],
    },
    "filesystems": {
        "name": "File Systems & Mounting",
        "explanation": """
File system management includes creating filesystems, mounting them,
and configuring persistent mounts via /etc/fstab. RHEL 8/9 defaults
to XFS but also supports ext4. You must know mkfs commands, mount/umount,
UUID-based fstab entries, and mount options. The exam tests creating
filesystems on partitions or LVs and making mounts persistent.
        """,
        "commands": [
            {
                "name": "Create XFS Filesystem",
                "syntax": "mkfs.xfs <device>",
                "example": "mkfs.xfs /dev/vgdata/lvdata",
                "flags": {
                    "mkfs.xfs": "Create XFS filesystem (RHEL default)",
                    "-f": "Force overwrite existing filesystem",
                    "-L": "Set filesystem label",
                },
            },
            {
                "name": "Create ext4 Filesystem",
                "syntax": "mkfs.ext4 <device>",
                "example": "mkfs.ext4 /dev/sdb1",
                "flags": {
                    "mkfs.ext4": "Create ext4 filesystem",
                    "-L": "Set filesystem label",
                    "-m": "Reserved blocks percentage",
                },
            },
            {
                "name": "Mount Filesystem (Temporary)",
                "syntax": "mount <device> <mountpoint>",
                "example": "mount /dev/vgdata/lvdata /mnt/data",
                "flags": {
                    "mount": "Mount filesystem now (not persistent)",
                    "-t": "Specify filesystem type",
                    "-o": "Mount options (ro, rw, noexec, etc.)",
                    "umount": "Unmount filesystem",
                },
            },
            {
                "name": "Get UUID",
                "syntax": "blkid <device>",
                "example": "blkid /dev/vgdata/lvdata",
                "flags": {
                    "blkid": "Show UUID and filesystem type",
                    "-s UUID -o value": "Show only UUID",
                    "lsblk -f": "Alternative to see UUIDs",
                },
            },
            {
                "name": "Add to fstab (Persistent)",
                "syntax": "echo 'UUID=<uuid> <mount> <type> defaults 0 0' >> /etc/fstab",
                "example": "echo 'UUID=abc123... /mnt/data xfs defaults 0 0' >> /etc/fstab; mount -a",
                "flags": {
                    "UUID=": "Use UUID (preferred over device path)",
                    "<mount>": "Mount point directory",
                    "<type>": "Filesystem type (xfs, ext4)",
                    "defaults": "Default mount options",
                    "0 0": "Dump and fsck order",
                    "mount -a": "Mount all fstab entries (test)",
                },
            },
        ],
        "common_mistakes": [
            "Using device path instead of UUID in fstab",
            "Mount point doesn't exist (must create with mkdir)",
            "Wrong filesystem type in fstab",
            "Not testing with 'mount -a' before reboot",
            "Typos in fstab can prevent boot",
        ],
        "exam_tricks": [
            "Always use UUID in fstab, not /dev/sdX",
            "Create mount point directory first (mkdir)",
            "Test with 'mount -a' to verify fstab syntax",
            "XFS is default in RHEL 8/9 unless specified otherwise",
        ],
    },
    "swap": {
        "name": "Swap Space Management",
        "explanation": """
Swap space extends available memory by using disk storage. When physical RAM
is full, inactive pages are moved to swap. RHEL supports swap partitions
and swap files.

KEY CONCEPTS:
  Swap Partition: Dedicated partition with swap filesystem
  Swap File:      Regular file configured as swap space
  Priority:       Higher priority swap is used first (-1 to 32767)
  vm.swappiness:  Kernel parameter controlling swap usage (0-100)

RECOMMENDED SWAP SIZE:
  RAM <= 2 GB:   2x RAM
  RAM 2-8 GB:    Equal to RAM
  RAM 8-64 GB:   At least 4 GB
  RAM > 64 GB:   At least 4 GB (or as needed)

KEY FILES:
  /etc/fstab     - Persistent swap configuration
  /proc/swaps    - Currently active swap spaces
  /proc/meminfo  - Memory and swap usage details
        """,
        "commands": [
            {
                "name": "Create Swap Partition",
                "syntax": "mkswap <device> && swapon <device>",
                "example": "mkswap /dev/sdb2\nswapon /dev/sdb2",
                "flags": {
                    "mkswap": "Format partition/file as swap",
                    "swapon": "Activate swap space",
                    "-L": "Set swap label",
                    "fdisk type 82": "Set partition type to Linux swap",
                },
            },
            {
                "name": "Create Swap File",
                "syntax": "dd if=/dev/zero of=<file> bs=1M count=<size> && mkswap <file> && swapon <file>",
                "example": "dd if=/dev/zero of=/swapfile bs=1M count=1024\nchmod 600 /swapfile\nmkswap /swapfile\nswapon /swapfile",
                "flags": {
                    "dd": "Create file of specified size",
                    "bs=1M count=1024": "1 GB swap file",
                    "chmod 600": "Required permissions for swap file",
                    "mkswap": "Format file as swap",
                    "swapon": "Activate swap file",
                },
            },
            {
                "name": "Persistent Swap (fstab)",
                "syntax": "UUID=<uuid>  swap  swap  defaults  0  0",
                "example": "# Partition swap:\nUUID=abc123...  swap  swap  defaults  0  0\n\n# File swap:\n/swapfile  swap  swap  defaults  0  0",
                "flags": {
                    "swap (mount)": "Mount point is 'swap' (not a directory)",
                    "swap (type)": "Filesystem type is 'swap'",
                    "defaults": "Standard swap options",
                    "pri=N": "Set priority (higher = used first)",
                },
            },
            {
                "name": "View and Manage Swap",
                "syntax": "swapon --show / free -h / swapoff",
                "example": "swapon --show\nfree -h\nswapoff /dev/sdb2",
                "flags": {
                    "swapon --show": "List active swap with details",
                    "swapon -s": "Alternative swap listing",
                    "free -h": "Show memory and swap usage",
                    "swapoff <device>": "Deactivate swap space",
                    "swapoff -a": "Deactivate all swap",
                },
            },
            {
                "name": "Create Swap on LVM",
                "syntax": "lvcreate -n <name> -L <size> <vg> && mkswap && swapon",
                "example": "lvcreate -n lvswap -L 2G vgdata\nmkswap /dev/vgdata/lvswap\nswapon /dev/vgdata/lvswap",
                "flags": {
                    "lvcreate": "Create logical volume for swap",
                    "mkswap": "Format LV as swap",
                    "swapon": "Activate LV swap",
                    "fstab": "Add UUID for persistence",
                },
            },
        ],
        "common_mistakes": [
            "Forgetting chmod 600 on swap file (insecure permissions)",
            "Not adding swap to /etc/fstab (lost on reboot)",
            "Using fallocate instead of dd for swap files on XFS (may not work)",
            "Forgetting mkswap before swapon (must format first)",
            "Wrong fstab format (mount point must be 'swap', not a directory)",
            "Trying to swapoff when swap is heavily in use (may hang)",
        ],
        "exam_tricks": [
            "Swap partition: create partition (type 82) -> mkswap -> swapon -> fstab",
            "Swap file: dd -> chmod 600 -> mkswap -> swapon -> fstab",
            "Always add to /etc/fstab for persistence",
            "Use UUID for partitions in fstab, path for files",
            "Verify with 'swapon --show' and 'free -h'",
            "LVM swap: create LV -> mkswap -> swapon -> fstab",
        ],
    },
    "network_storage": {
        "name": "Network Storage (NFS/CIFS/Autofs)",
        "explanation": """
Network storage allows mounting remote filesystems. NFS is for Linux-to-Linux,
CIFS/SMB is for Windows shares. Autofs provides on-demand mounting.

NFS (Network File System):
  - Native Linux network filesystem
  - Uses showmount to discover exports
  - Mount options: rw, ro, sync, soft, hard

CIFS/SMB (Common Internet File System):
  - Windows-compatible network shares
  - Requires cifs-utils package
  - Uses credentials file for security

AUTOFS:
  - Automatic mount on access
  - Unmounts after timeout
  - Configured in /etc/auto.master

KEY FILES:
  /etc/fstab              - Persistent mounts
  /etc/auto.master        - Autofs master map
  /etc/auto.*             - Autofs submaps
  /etc/cifs-credentials   - CIFS credentials file
        """,
        "commands": [
            {
                "name": "List NFS Exports",
                "syntax": "showmount -e <server>",
                "example": "showmount -e nfs.example.com",
                "flags": {
                    "-e": "Show exports",
                    "-a": "Show all mounts",
                    "Requires": "nfs-utils package",
                },
            },
            {
                "name": "Mount NFS Share",
                "syntax": "mount -t nfs <server>:<export> <mountpoint>",
                "example": "mount -t nfs server:/data /mnt/nfs",
                "flags": {
                    "-t nfs": "NFS filesystem type",
                    "-o rw": "Read-write mount",
                    "-o ro": "Read-only mount",
                    "-o sync": "Synchronous writes",
                },
            },
            {
                "name": "NFS fstab Entry",
                "syntax": "server:/export /mount nfs defaults 0 0",
                "example": "nfs.example.com:/data /mnt/nfs nfs defaults,_netdev 0 0",
                "flags": {
                    "_netdev": "Wait for network (recommended)",
                    "defaults": "Standard mount options",
                    "rw,sync": "Custom options",
                },
            },
            {
                "name": "Mount CIFS Share",
                "syntax": "mount -t cifs //<server>/<share> <mountpoint> -o credentials=<file>",
                "example": "mount -t cifs //server/share /mnt/cifs -o credentials=/etc/cifs-creds",
                "flags": {
                    "-t cifs": "CIFS filesystem type",
                    "-o credentials=": "Credentials file path",
                    "-o username=,password=": "Inline credentials (insecure)",
                },
            },
            {
                "name": "CIFS Credentials File",
                "syntax": "/etc/cifs-credentials",
                "example": "username=smbuser\npassword=secret\ndomain=WORKGROUP\n\nchmod 600 /etc/cifs-credentials",
                "flags": {
                    "username=": "SMB username",
                    "password=": "SMB password",
                    "domain=": "Windows domain",
                    "chmod 600": "Secure the file!",
                },
            },
            {
                "name": "Configure Autofs",
                "syntax": "Edit /etc/auto.master and submaps",
                "example": "# /etc/auto.master\n/mnt/auto  /etc/auto.nfs\n\n# /etc/auto.nfs\ndata  -rw,sync  server:/data",
                "flags": {
                    "/etc/auto.master": "Master map file",
                    "Mount point": "Parent directory",
                    "Map file": "Submap with mount definitions",
                    "Key": "Subdirectory name",
                    "Options": "Mount options",
                    "Location": "server:/export",
                },
            },
            {
                "name": "Autofs Home Directories",
                "syntax": "/etc/auto.master with wildcard",
                "example": "# /etc/auto.master\n/home/remote  /etc/auto.home\n\n# /etc/auto.home\n*  -rw  nfs:/home/&",
                "flags": {
                    "*": "Wildcard - match any key",
                    "&": "Substitute matched key",
                    "Result": "/home/remote/user mounts nfs:/home/user",
                },
            },
            {
                "name": "Enable Autofs",
                "syntax": "systemctl enable --now autofs",
                "example": "systemctl enable --now autofs",
                "flags": {
                    "enable --now": "Enable and start",
                    "restart": "Apply config changes",
                    "status": "Check service status",
                },
            },
        ],
        "common_mistakes": [
            "Forgetting _netdev option for network mounts in fstab",
            "Wrong permissions on credentials file (must be 600)",
            "Not installing cifs-utils for CIFS mounts",
            "Autofs syntax errors (check with automount -v)",
            "Not restarting autofs after config changes",
        ],
        "exam_tricks": [
            "NFS: showmount -e server to see exports",
            "CIFS: use credentials file, chmod 600",
            "Autofs: * and & for home directory wildcards",
            "fstab: use _netdev for network filesystems",
            "Test autofs: ls /mnt/auto/mountname triggers mount",
        ],
    },
}
