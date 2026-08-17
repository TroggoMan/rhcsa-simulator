"""
Network storage tasks for RHCSA exam (NFS, Autofs, SMB/CIFS).
"""

import random
import logging
from tasks.base import BaseTask
from tasks.registry import TaskRegistry
from core.validator import ValidationCheck, ValidationResult
from validators.safe_executor import execute_safe
from validators.file_validators import validate_file_exists, validate_file_contains


logger = logging.getLogger(__name__)


def _nfs_config():
    """Return the configured remote NFS server dict, or None."""
    try:
        from core import nfs_server
        return nfs_server.load_config()
    except Exception:
        return None


def _nfs_source(mount_point):
    """(source, fstype) for an exact mountpoint via findmnt, else (None, None)."""
    res = execute_safe(['findmnt', '-n', '-o', 'SOURCE,FSTYPE', mount_point])
    if res.success and res.stdout.strip():
        parts = res.stdout.split()
        if len(parts) >= 2:
            return parts[0], parts[1]
    return None, None


@TaskRegistry.register("network_storage")
class MountNFSShareTask(BaseTask):
    """Mount an NFS share manually."""

    requires_nfs_server = True

    def __init__(self):
        super().__init__(
            id="nfs_mount_001",
            category="network_storage",
            difficulty="medium",
            points=10
        )
        self.tags = ['nfs', 'network-storage']
        self.exam_tips = [
            "Use showmount -e to discover available NFS exports",
            "Create mount point before mounting (mkdir -p)",
            "NFS mount syntax: mount -t nfs server:/export /mountpoint",
            "Common NFS options: rw, sync, hard, intr, timeo, retrans",
        ]
        self.nfs_server = None
        self.nfs_export = None
        self.mount_point = None

    def generate(self, **params):
        """Generate NFS mount task. Uses the real configured NFS server/export
        when Setup has provisioned one, otherwise a placeholder."""
        cfg = _nfs_config()
        if cfg and cfg.get('exports'):
            self.nfs_server = params.get('server', cfg['host'])
            self.nfs_export = params.get('export', cfg['exports'][0])
        else:
            self.nfs_server = params.get('server', 'server1.example.com')
            self.nfs_export = params.get('export', '/share/data')
        self.mount_point = params.get('mount_point', '/mnt/nfsdata')

        self.description = (
            f"Mount an NFS share:\n"
            f"  - NFS Server: {self.nfs_server}\n"
            f"  - Export path: {self.nfs_export}\n"
            f"  - Mount point: {self.mount_point}\n"
            f"  - Create mount point if needed\n"
            f"  - Mount read-write"
        )

        self.hints = [
            f"Discover exports: showmount -e {self.nfs_server}",
            f"Create mount point: mkdir -p {self.mount_point}",
            f"Mount: mount -t nfs {self.nfs_server}:{self.nfs_export} {self.mount_point}",
            "Common options: -o rw,sync,hard,intr",
            f"Verify: mount | grep {self.mount_point}"
        ]

        return self

    def validate(self):
        """Validate NFS mount."""
        checks = []
        total_points = 0

        import os

        # Check 1: Mount point exists (3 points)
        if os.path.isdir(self.mount_point):
            checks.append(ValidationCheck(
                name="mount_point_exists",
                passed=True,
                points=3,
                message=f"Mount point {self.mount_point} exists"
            ))
            total_points += 3
        else:
            checks.append(ValidationCheck(
                name="mount_point_exists",
                passed=False,
                points=0,
                max_points=3,
                message=f"Mount point {self.mount_point} does not exist"
            ))
            return ValidationResult(self.id, False, total_points, self.points, checks)

        # Check 2: NFS is mounted (7 points). With a real configured server we
        # verify the mount actually originates from server:export; otherwise we
        # fall back to a looser "an NFS filesystem is mounted here" check.
        source, fstype = _nfs_source(self.mount_point)
        is_nfs = bool(fstype) and fstype.startswith('nfs')
        expected = f"{self.nfs_server}:{self.nfs_export}"

        if is_nfs and source and source.endswith(f":{self.nfs_export}"):
            checks.append(ValidationCheck(
                name="nfs_mounted",
                passed=True,
                points=7,
                message=f"{source} ({fstype}) is mounted at {self.mount_point}"
            ))
            total_points += 7
        elif is_nfs:
            checks.append(ValidationCheck(
                name="nfs_mounted",
                passed=False,
                points=4,
                max_points=7,
                message=f"An NFS mount is present but its source ({source}) is not "
                        f"the expected {expected}"
            ))
            total_points += 4
        else:
            checks.append(ValidationCheck(
                name="nfs_mounted",
                passed=False,
                points=0,
                max_points=7,
                message=f"No NFS filesystem is mounted at {self.mount_point} "
                        f"(expected {expected})"
            ))

        passed = total_points >= (self.points * 0.7)
        return ValidationResult(self.id, passed, total_points, self.points, checks)


@TaskRegistry.register("network_storage")
class PersistentNFSMountTask(BaseTask):
    """Configure persistent NFS mount in fstab."""

    requires_nfs_server = True

    def __init__(self):
        super().__init__(
            id="nfs_fstab_001",
            category="network_storage",
            difficulty="medium",
            points=12
        )
        self.requires_persistence = True
        self.tags = ['nfs', 'fstab', 'network-storage']
        self.exam_tips = [
            "fstab format: server:/export /mountpoint nfs defaults,_netdev 0 0",
            "_netdev is CRITICAL for network mounts - delays mount until network is up",
            "Use blkid or lsblk -f to get UUIDs for local filesystems (not for NFS)",
            "Test fstab without reboot using: mount -a",
            "Wrong fstab can prevent boot - always test before rebooting",
        ]
        self.nfs_server = None
        self.nfs_export = None
        self.mount_point = None

    def generate(self, **params):
        """Generate persistent NFS mount task (uses the real configured server
        and export when available)."""
        cfg = _nfs_config()
        if cfg and cfg.get('exports'):
            self.nfs_server = params.get('server', cfg['host'])
            # Prefer the second export ('shared') so it differs from the basic
            # mount task; fall back to the first.
            default_export = cfg['exports'][1] if len(cfg['exports']) > 1 else cfg['exports'][0]
            self.nfs_export = params.get('export', default_export)
        else:
            self.nfs_server = params.get('server', 'nfsserver.example.com')
            self.nfs_export = params.get('export', '/exports/shared')
        self.mount_point = params.get('mount_point', '/mnt/shared')

        self.description = (
            f"Configure persistent NFS mount:\n"
            f"  - NFS Server: {self.nfs_server}\n"
            f"  - Export: {self.nfs_export}\n"
            f"  - Mount point: {self.mount_point}\n"
            f"  - Add to /etc/fstab for persistence\n"
            f"  - Use _netdev option (required for network mounts)\n"
            f"  - Mount should work after reboot"
        )

        self.hints = [
            f"Create mount point: mkdir -p {self.mount_point}",
            f"fstab entry format: {self.nfs_server}:{self.nfs_export} {self.mount_point} nfs defaults,_netdev 0 0",
            "Edit /etc/fstab with vim or nano",
            "_netdev waits for network before mounting",
            "Test without reboot: mount -a"
        ]

        return self

    def validate(self):
        """Validate persistent NFS mount."""
        checks = []
        total_points = 0

        import os

        # Check 1: Mount point exists (2 points)
        if os.path.isdir(self.mount_point):
            checks.append(ValidationCheck(
                name="mount_point_exists",
                passed=True,
                points=2,
                message="Mount point exists"
            ))
            total_points += 2
        else:
            checks.append(ValidationCheck(
                name="mount_point_exists",
                passed=False,
                points=0,
                max_points=2,
                message="Mount point does not exist"
            ))

        # Check 2: fstab entry exists (6 points)
        fstab_has_entry = False
        has_netdev = False

        if validate_file_contains('/etc/fstab', self.mount_point):
            try:
                with open('/etc/fstab', 'r') as f:
                    for line in f:
                        if self.mount_point in line and not line.strip().startswith('#'):
                            fstab_has_entry = True
                            if '_netdev' in line:
                                has_netdev = True
                            break
            except Exception:
                pass

        if fstab_has_entry:
            if has_netdev:
                checks.append(ValidationCheck(
                    name="fstab_entry",
                    passed=True,
                    points=6,
                    message="fstab entry with _netdev option exists"
                ))
                total_points += 6
            else:
                checks.append(ValidationCheck(
                    name="fstab_entry",
                    passed=True,
                    points=4,
                    message="fstab entry exists but missing _netdev option"
                ))
                total_points += 4
        else:
            checks.append(ValidationCheck(
                name="fstab_entry",
                passed=False,
                points=0,
                max_points=6,
                message="No fstab entry for this mount"
            ))

        # Check 3: Actually mounted (4 points) — verify it's really NFS from the
        # expected export when we can, else accept any mount at the point.
        source, fstype = _nfs_source(self.mount_point)
        if source and fstype and fstype.startswith('nfs') and source.endswith(f":{self.nfs_export}"):
            checks.append(ValidationCheck(
                name="is_mounted",
                passed=True,
                points=4,
                message=f"Mount is active: {source} ({fstype})"
            ))
            total_points += 4
        elif source:
            checks.append(ValidationCheck(
                name="is_mounted",
                passed=True,
                points=2,
                max_points=4,
                message=f"Mounted ({source}) but not the expected "
                        f"{self.nfs_server}:{self.nfs_export}"
            ))
            total_points += 2
        else:
            checks.append(ValidationCheck(
                name="is_mounted",
                passed=False,
                points=0,
                max_points=4,
                message="Not currently mounted (try: mount -a)"
            ))

        passed = total_points >= (self.points * 0.7)
        return ValidationResult(self.id, passed, total_points, self.points, checks)


@TaskRegistry.register("network_storage")
class ConfigureAutofsTask(BaseTask):
    """Configure autofs for automatic mounting."""

    requires_nfs_server = True

    def __init__(self):
        super().__init__(
            id="autofs_basic_001",
            category="network_storage",
            difficulty="exam",
            points=15
        )
        self.requires_persistence = True
        self.tags = ['autofs', 'nfs', 'network-storage']
        self.exam_tips = [
            "Install autofs package first: dnf install autofs -y",
            "Two files needed: /etc/auto.master (master map) and /etc/auto.* (mount map)",
            "Master map format: /mountpoint /etc/auto.mapname",
            "Mount map format: subdirectory -options server:/export",
            "Enable and start autofs service: systemctl enable --now autofs",
            "Test by accessing the mount point (triggers auto-mount)",
            "After config changes: systemctl restart autofs",
        ]
        self.nfs_server = None
        self.nfs_export = None
        self.autofs_mount = None
        self.map_name = None
        self.map_type = None

    def generate(self, **params):
        """Generate autofs configuration task.

        Two variants, phrased the explicit way Red Hat words them ("...so that
        /X is an automount directory" = indirect; "...so that /X is
        automatically mounted" = direct). Indirect is drawn 3:1 — it is by far
        the more commonly reported exam task (wildcard/subdirectory mounts);
        direct maps appear occasionally, so they stay in rotation.
        """
        cfg = _nfs_config()
        self.map_type = params.get('map_type') or random.choices(
            ['indirect', 'direct'], weights=[3, 1])[0]

        def _pick_export(suffix, fallback):
            if cfg and cfg.get('exports'):
                for e in cfg['exports']:
                    if e.rstrip('/').endswith(suffix):
                        return e
                return cfg['exports'][0]
            return fallback

        if cfg and cfg.get('exports'):
            self.nfs_server = params.get('server', cfg['host'])
        else:
            self.nfs_server = params.get('server', 'nfs.example.com')

        if self.map_type == 'indirect':
            # The 'shared' export ships first-level subdirectories (docs,
            # tools, projects) that serve as the indirect keys.
            self.nfs_export = params.get('export',
                                         _pick_export('/shared', '/export/shared'))
            self.autofs_mount = params.get('mount', '/shares')
            self.map_name = params.get('map', 'auto.shares')

            self.description = (
                f"Configure autofs so that {self.autofs_mount} is an automount "
                f"directory:\n"
                f"  - NFS Server: {self.nfs_server}\n"
                f"  - NFS Export: {self.nfs_export} (contains subdirectories "
                f"such as docs, tools, projects)\n"
                f"  - Accessing {self.autofs_mount}/<name> must automount "
                f"{self.nfs_server}:{self.nfs_export}/<name>\n"
                f"  - Use a wildcard key so any subdirectory works without "
                f"further config changes\n"
                f"  - Mounts appear on access and unmount after the idle timeout\n"
                f"  - autofs service must be running"
            )

            self.hints = [
                "Install autofs: dnf install autofs -y",
                f"Add to /etc/auto.master: {self.autofs_mount} /etc/{self.map_name}",
                f"Create /etc/{self.map_name} with: * -rw {self.nfs_server}:{self.nfs_export}/&",
                "* matches the accessed name, & substitutes it into the export path",
                "Start service: systemctl enable --now autofs",
                f"Test: ls {self.autofs_mount}/docs"
            ]
        else:
            self.nfs_export = params.get('export',
                                         _pick_export('/data', '/export/data'))
            self.autofs_mount = params.get('mount', '/data')
            self.map_name = params.get('map', 'auto.data')

            self.description = (
                f"Configure autofs so that {self.autofs_mount} is automatically "
                f"mounted from an NFS export:\n"
                f"  - NFS Server: {self.nfs_server}\n"
                f"  - NFS Export: {self.nfs_export}\n"
                f"  - {self.autofs_mount} itself is the mount target (a direct "
                f"map, not a directory of automounts)\n"
                f"  - The export must mount on access and unmount after the idle timeout\n"
                f"  - autofs service must be running"
            )

            self.hints = [
                "Install autofs: dnf install autofs -y",
                f"Direct maps are declared with /- ; add to /etc/auto.master: /- /etc/{self.map_name}",
                f"Create /etc/{self.map_name} with: {self.autofs_mount} -rw {self.nfs_server}:{self.nfs_export}",
                "An indirect-style master entry (mount-point + map) can never match "
                "an absolute key like this one",
                "Start service: systemctl enable --now autofs",
                f"Test: ls {self.autofs_mount}"
            ]

        return self

    def validate(self):
        """Validate autofs configuration."""
        checks = []
        total_points = 0

        # Check 1: autofs service running (4 points)
        result = execute_safe(['systemctl', 'is-active', 'autofs'])
        if result.success and result.stdout.strip() == 'active':
            checks.append(ValidationCheck(
                name="autofs_running",
                passed=True,
                points=4,
                message="autofs service is running"
            ))
            total_points += 4
        else:
            checks.append(ValidationCheck(
                name="autofs_running",
                passed=False,
                points=0,
                max_points=4,
                message="autofs service is not running"
            ))

        # Check 2: autofs enabled (2 points)
        result = execute_safe(['systemctl', 'is-enabled', 'autofs'])
        if result.success and 'enabled' in result.stdout:
            checks.append(ValidationCheck(
                name="autofs_enabled",
                passed=True,
                points=2,
                message="autofs service is enabled"
            ))
            total_points += 2
        else:
            checks.append(ValidationCheck(
                name="autofs_enabled",
                passed=False,
                points=0,
                max_points=2,
                message="autofs service is not enabled"
            ))

        # Check 3: the right kind of map is declared (5 points). Direct maps
        # need a /- master line plus the absolute mount point as a map key;
        # indirect maps need the parent directory as the master entry plus a
        # wildcard (or explicit subdirectory) key. Using the wrong style reads
        # plausibly but can never match, so it only earns partial credit.
        import os
        import glob

        def _noncomment_lines(path):
            try:
                with open(path) as f:
                    return [ln.strip() for ln in f
                            if ln.strip() and not ln.strip().startswith('#')]
            except OSError:
                return []

        master_lines = _noncomment_lines('/etc/auto.master')
        for extra in sorted(glob.glob('/etc/auto.master.d/*')):
            if os.path.isfile(extra):
                master_lines += _noncomment_lines(extra)

        map_lines = [
            ln
            for path in glob.glob('/etc/auto.*') if os.path.isfile(path)
            and os.path.basename(path) != 'auto.master'
            for ln in _noncomment_lines(path)
        ]

        has_direct_decl = any(ln.split()[0] == '/-' for ln in master_lines)
        has_indirect_decl = any(ln.split()[0] == self.autofs_mount
                                for ln in master_lines)
        abs_key_in_map = any(ln.split()[0] == self.autofs_mount
                             for ln in map_lines if ln.split())
        wildcard_key_in_map = any(
            ln.split()[0] == '*' and self.nfs_server in ln
            for ln in map_lines if ln.split())

        if self.map_type == 'direct':
            ok = has_direct_decl and abs_key_in_map
            wrong_style = has_indirect_decl
            fix = (f"{self.autofs_mount} itself is the mount target — declare "
                   f"a direct map (/- /etc/{self.map_name}) with "
                   f"{self.autofs_mount} as the key")
            ok_msg = f"Direct map declared (/-) with key {self.autofs_mount}"
        else:
            ok = has_indirect_decl and wildcard_key_in_map
            wrong_style = has_direct_decl or (has_indirect_decl
                                              and not wildcard_key_in_map)
            fix = (f"{self.autofs_mount} is an automount directory — declare "
                   f"'{self.autofs_mount} /etc/{self.map_name}' in the master "
                   f"map with a wildcard key "
                   f"(* -rw {self.nfs_server}:{self.nfs_export}/&)")
            ok_msg = (f"Indirect map declared for {self.autofs_mount} with a "
                      f"wildcard key")

        if ok:
            checks.append(ValidationCheck(
                name="master_entry",
                passed=True,
                points=5,
                message=ok_msg
            ))
            total_points += 5
        elif wrong_style:
            checks.append(ValidationCheck(
                name="master_entry",
                passed=False,
                points=2,
                max_points=5,
                message=f"Map style doesn't match the question — {fix}"
            ))
            total_points += 2
        else:
            checks.append(ValidationCheck(
                name="master_entry",
                passed=False,
                points=0,
                max_points=5,
                message="No autofs master map entry found"
            ))

        # Check 4: Map file exists (4 points)
        map_file = f'/etc/{self.map_name}'
        if validate_file_exists(map_file):
            checks.append(ValidationCheck(
                name="map_file",
                passed=True,
                points=4,
                message=f"Map file {map_file} exists"
            ))
            total_points += 4
        else:
            # Check for any auto.* file
            result = execute_safe(['ls', '/etc/auto.*'])
            if result.success:
                checks.append(ValidationCheck(
                    name="map_file",
                    passed=True,
                    points=2,
                    message="Some autofs map files exist"
                ))
                total_points += 2
            else:
                checks.append(ValidationCheck(
                    name="map_file",
                    passed=False,
                    points=0,
                    max_points=4,
                    message="No autofs map file found"
                ))

        passed = total_points >= (self.points * 0.7)
        return ValidationResult(self.id, passed, total_points, self.points, checks)


@TaskRegistry.register("network_storage")
class AutofsHomeDirectoriesTask(BaseTask):
    """Configure autofs for NFS home directories."""

    requires_nfs_server = True

    def __init__(self):
        super().__init__(
            id="autofs_home_001",
            category="network_storage",
            difficulty="exam",
            points=18
        )
        self.requires_persistence = True
        self.tags = ['autofs', 'nfs', 'network-storage', 'home-directories']
        self.exam_tips = [
            "Wildcard substitution: * in map matches any name, & substitutes matched value",
            "Example: * -rw,sync server:/export/& mounts /mountpoint/user to server:/export/user",
            "For home dirs: /home/guests /etc/auto.home in master map",
            "In auto.home: * -rw,sync server:/home/&",
            "Test by cd /home/guests/username - should auto-mount",
            "Check mounts: mount | grep autofs",
        ]
        self.nfs_server = None
        self.home_export = None

    def generate(self, **params):
        """Generate autofs home directories task."""
        cfg = _nfs_config()
        if cfg and cfg.get('exports'):
            self.nfs_server = params.get('server', cfg['host'])
            # The 'guests' export ships per-user homes (user1..user3) for
            # exactly this wildcard task; fall back to the first export.
            guests = [e for e in cfg['exports']
                      if e.rstrip('/').endswith('/guests')]
            self.home_export = params.get(
                'export', guests[0] if guests else cfg['exports'][0])
        else:
            self.nfs_server = params.get('server', 'ldap.example.com')
            self.home_export = params.get('export', '/home/guests')

        self.description = (
            f"Configure autofs so that /home/guests is an automount directory "
            f"for user home directories:\n"
            f"  - NFS Server: {self.nfs_server}\n"
            f"  - Export base: {self.home_export}\n"
            f"  - /home/guests/<user> must auto-mount from "
            f"{self.nfs_server}:{self.home_export}/<user>\n"
            f"  - Subdirectories appear on demand (an indirect map with a "
            f"wildcard key)\n"
            f"  - Service must be running and enabled"
        )

        self.hints = [
            "Add to /etc/auto.master: /home/guests /etc/auto.home",
            f"Create /etc/auto.home: * -rw,sync {self.nfs_server}:{self.home_export}/&",
            "The * matches any subdirectory, & substitutes the matched name",
            "Restart autofs: systemctl restart autofs",
            "Test: ls /home/guests/testuser (should trigger mount)"
        ]

        return self

    def validate(self):
        """Validate autofs home directories."""
        checks = []
        total_points = 0

        # Check 1: autofs service running and enabled (4 points)
        result_active = execute_safe(['systemctl', 'is-active', 'autofs'])
        result_enabled = execute_safe(['systemctl', 'is-enabled', 'autofs'])

        if (result_active.success and result_active.stdout.strip() == 'active' and
            result_enabled.success and 'enabled' in result_enabled.stdout):
            checks.append(ValidationCheck(
                name="autofs_service",
                passed=True,
                points=4,
                message="autofs is running and enabled"
            ))
            total_points += 4
        elif result_active.success and result_active.stdout.strip() == 'active':
            checks.append(ValidationCheck(
                name="autofs_service",
                passed=True,
                points=2,
                message="autofs running but not enabled"
            ))
            total_points += 2
        else:
            checks.append(ValidationCheck(
                name="autofs_service",
                passed=False,
                points=0,
                max_points=4,
                message="autofs service not running"
            ))

        # Check 2: auto.master has /home entry (6 points)
        home_entry = False
        try:
            with open('/etc/auto.master', 'r') as f:
                content = f.read()
                if '/home' in content and 'auto.' in content:
                    home_entry = True
        except Exception:
            pass

        if home_entry:
            checks.append(ValidationCheck(
                name="master_home",
                passed=True,
                points=6,
                message="auto.master has /home configuration"
            ))
            total_points += 6
        else:
            checks.append(ValidationCheck(
                name="master_home",
                passed=False,
                points=0,
                max_points=6,
                message="auto.master missing /home configuration"
            ))

        # Check 3: Map file with wildcard (8 points)
        wildcard_found = False
        for map_file in ['/etc/auto.home', '/etc/auto.guests', '/etc/auto.nfs']:
            if validate_file_exists(map_file):
                try:
                    with open(map_file, 'r') as f:
                        content = f.read()
                        if '*' in content and '&' in content:
                            wildcard_found = True
                            break
                except Exception:
                    pass

        if wildcard_found:
            checks.append(ValidationCheck(
                name="wildcard_map",
                passed=True,
                points=8,
                message="Map file with wildcard substitution found"
            ))
            total_points += 8
        else:
            checks.append(ValidationCheck(
                name="wildcard_map",
                passed=False,
                points=0,
                max_points=8,
                message="No wildcard (*) map for home directories"
            ))

        passed = total_points >= (self.points * 0.7)
        return ValidationResult(self.id, passed, total_points, self.points, checks)
