"""
Distro and system-resource identification.

Everything in the simulator that decides "is this thing the candidate's
practice storage, or is it the box's own operating system?" must go through
here.

WHY THIS EXISTS
---------------
The simulator used to answer that question with a hardcoded list of volume
group names::

    system_vgs = {'rl', 'rl00', 'rhel', 'centos', 'fedora'}

Anaconda names the root VG after the product: RHEL -> ``rhel``, Rocky ->
``rl``, CentOS -> ``centos`` ... and AlmaLinux -> ``almalinux``, which was
NOT in that list. On an AlmaLinux install the box's own root VG therefore
looked like a spare practice VG, so ``get_practice_vg()`` handed LVM tasks
the system VG and the cleanup pass considered the system LVs fair game.

A name list can only ever describe the distros someone remembered. So the
system VGs are *detected* here — by asking which VGs actually back the
mounted filesystems and active swap — and the name list survives only as a
fallback for when LVM tooling can't be queried.

Everything is cached; call reset_cache() in tests.
"""

import glob
import logging
import os
import re
import subprocess

logger = logging.getLogger(__name__)

OS_RELEASE_PATHS = ('/etc/os-release', '/usr/lib/os-release')

# RHEL-family distros this simulator is written for: os-release ID -> label.
SUPPORTED_IDS = {
    'rhel': 'Red Hat Enterprise Linux',
    'almalinux': 'AlmaLinux',
    'rocky': 'Rocky Linux',
    'centos': 'CentOS Stream',
    'ol': 'Oracle Linux',
    'fedora': 'Fedora',
}

# EX200 v10 targets RHEL 10; 9 is close enough to practise on.
SUPPORTED_MAJORS = (9, 10)

# Fallback only — used when LVM can't be queried (no lvm2, non-root, CI
# container). Detection via mounted filesystems is authoritative.
KNOWN_SYSTEM_VG_NAMES = frozenset({
    'rl', 'rl00', 'rl_root', 'rhel', 'rhel00', 'centos', 'fedora',
    'almalinux', 'alma', 'rocky', 'ol', 'oracle', 'vg_root', 'vg00',
    'vg_system', 'system',
})

# Mountpoints that belong to the OS. If one of these lives on an LV, that
# LV's VG is a system VG. /srv, /mnt, /media, /export deliberately absent —
# those are where practice filesystems get mounted.
SYSTEM_MOUNTPOINTS = (
    '/', '/boot', '/boot/efi', '/home', '/usr', '/var', '/var/log',
    '/var/tmp', '/opt', '/tmp', '/etc',
)

_cache = {}


def reset_cache():
    """Drop every cached probe result. Call from tests, or after the
    candidate has changed storage layout in a way we need to re-read."""
    _cache.clear()


# ── os-release ──────────────────────────────────────────────────────────────

def os_release():
    """Parsed /etc/os-release as a dict (empty if unreadable)."""
    if 'os_release' in _cache:
        return _cache['os_release']

    data = {}
    for path in OS_RELEASE_PATHS:
        try:
            with open(path) as f:
                content = f.read()
        except (IOError, OSError):
            continue
        for line in content.splitlines():
            line = line.strip()
            if not line or line.startswith('#') or '=' not in line:
                continue
            key, _, value = line.partition('=')
            data[key.strip()] = value.strip().strip('"').strip("'")
        if data:
            break

    _cache['os_release'] = data
    return data


def distro_id():
    """os-release ID, lowercased ('almalinux', 'rocky', 'rhel'...). '' if unknown."""
    return os_release().get('ID', '').lower()


def distro_like():
    """os-release ID_LIKE as a list ('rhel', 'centos', 'fedora')."""
    return os_release().get('ID_LIKE', '').lower().split()


def distro_version():
    """os-release VERSION_ID ('10.0', '9.5'). '' if unknown."""
    return os_release().get('VERSION_ID', '')


def distro_major():
    """Major version as an int, or None if it can't be parsed."""
    match = re.match(r'(\d+)', distro_version())
    return int(match.group(1)) if match else None


def is_rhel_family():
    """True if this is RHEL or a rebuild of it."""
    ids = set(distro_like())
    ids.add(distro_id())
    return bool(ids & {'rhel', 'centos', 'fedora'}) or distro_id() in SUPPORTED_IDS


def distro_name():
    """Human-readable distro name for display."""
    rel = os_release()
    return rel.get('PRETTY_NAME') or rel.get('NAME') or 'unknown Linux'


# ── LVM / block-device probing ──────────────────────────────────────────────

def _run(cmd, timeout=10):
    """Run a read-only probe. Returns stdout on success, None on any failure —
    probes must never raise into a task or a validator."""
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError) as e:
        logger.debug("probe failed (%s): %s", ' '.join(cmd), e)
        return None
    if result.returncode != 0:
        return None
    return result.stdout


def vg_of_device(device):
    """VG name backing a block device, or None if it isn't an LV.

    Handles /dev/mapper/vg-lv, /dev/vg/lv and /dev/dm-N alike — lvs resolves
    all three, which is why we ask lvs instead of parsing the mapper name
    (device-mapper doubles literal dashes, so parsing gets it wrong for any
    VG whose name contains one).
    """
    if not device or not device.startswith('/dev/'):
        return None
    out = _run(['lvs', '--noheadings', '-o', 'vg_name', device], timeout=5)
    if out is None:
        return None
    name = out.strip()
    return name or None


def _source_of_mountpoint(mountpoint):
    """Backing device for a mountpoint, or None if it isn't a mountpoint."""
    out = _run(['findmnt', '-no', 'SOURCE', '--target', mountpoint], timeout=5)
    if out is None:
        return None
    return out.strip().splitlines()[0].strip() if out.strip() else None


def _active_swap_devices():
    """Devices listed in /proc/swaps."""
    devices = []
    try:
        with open('/proc/swaps') as f:
            for line in f.readlines()[1:]:
                parts = line.split()
                if parts and parts[0].startswith('/dev/'):
                    devices.append(parts[0])
    except (IOError, OSError):
        pass
    return devices


def detected_system_vgs():
    """VGs proven to back the running OS: every VG holding a system
    mountpoint or active swap. Empty set if nothing could be probed."""
    found = set()

    for mountpoint in SYSTEM_MOUNTPOINTS:
        if not os.path.exists(mountpoint):
            continue
        source = _source_of_mountpoint(mountpoint)
        vg = vg_of_device(source) if source else None
        if vg:
            found.add(vg)

    for device in _active_swap_devices():
        vg = vg_of_device(device)
        if vg:
            found.add(vg)

    return found


def system_vgs():
    """Volume groups that belong to the operating system and must NEVER be
    handed to a task or touched by cleanup.

    Union of what was detected from live mounts/swap and the known-names
    fallback, so an unprobeable box still gets the old (partial) protection
    rather than none at all.
    """
    if 'system_vgs' in _cache:
        return _cache['system_vgs']

    detected = detected_system_vgs()
    if not detected:
        logger.debug("no system VGs detected from mounts; using name fallback only")

    vgs = frozenset(detected | set(KNOWN_SYSTEM_VG_NAMES) | _distro_vg_guesses())
    _cache['system_vgs'] = vgs
    return vgs


def _distro_vg_guesses():
    """VG names anaconda would plausibly have picked on THIS distro, so a
    distro we've never seen still gets its most likely root VG protected."""
    guesses = set()
    did = distro_id()
    if did:
        guesses.add(did)
        guesses.add(did.replace('linux', ''))
        major = distro_major()
        if major is not None:
            guesses.add('%s%d' % (did, major))
    return {g for g in guesses if g}


def is_system_vg(vg_name):
    """True if this VG backs the OS. Unknown/empty names are treated as
    system — refusing to touch something we can't identify is the safe
    default when the alternative is lvremove."""
    if not vg_name or not vg_name.strip():
        return True
    return vg_name.strip() in system_vgs()


def system_pvs():
    """PV device paths belonging to system VGs."""
    if 'system_pvs' in _cache:
        return _cache['system_pvs']

    pvs = set()
    out = _run(['pvs', '--noheadings', '-o', 'pv_name,vg_name'], timeout=10)
    if out:
        protected = system_vgs()
        for line in out.strip().splitlines():
            parts = line.split()
            if len(parts) >= 2 and parts[1].strip() in protected:
                pvs.add(parts[0].strip())

    _cache['system_pvs'] = frozenset(pvs)
    return _cache['system_pvs']


def _parent_disk(device):
    """Whole disk ultimately backing a device.

    '/dev/nvme0n1p3' -> '/dev/nvme0n1', and crucially
    '/dev/mapper/almalinux-root' -> '/dev/nvme0n1', walking LV -> partition
    -> disk in one step.

    Uses `lsblk -rnso NAME`, which prints the device's ancestry inverted
    (device first, whole disk last). PKNAME is not usable here: for a
    partition that has LVM children it reports the parent of each *child*
    row, so the first line is the partition itself rather than its disk.
    """
    if not device:
        return None
    out = _run(['lsblk', '-rnso', 'NAME', device], timeout=5)
    if not out or not out.strip():
        return None
    lines = [l.strip() for l in out.strip().splitlines() if l.strip()]
    if not lines:
        return None
    top = lines[-1]
    disk = '/dev/' + top
    # The device is already a whole disk — it has no parent.
    return None if disk == device else disk


def system_disks():
    """Whole disks the OS lives on — the disks holding system PVs, plus the
    disk backing / and /boot for non-LVM installs.

    Replaces guessing by device name (vda/sda/nvme0n1/xvda), which is wrong
    on any box whose OS isn't on the first disk.
    """
    if 'system_disks' in _cache:
        return _cache['system_disks']

    disks = set()

    sources = set(system_pvs())
    for mountpoint in ('/', '/boot', '/boot/efi'):
        source = _source_of_mountpoint(mountpoint)
        if source and source.startswith('/dev/'):
            sources.add(source)

    for source in sources:
        parent = _parent_disk(source)
        if parent:
            disks.add(parent)
        elif re.match(r'^/dev/[a-z0-9]+$', source) and not source.startswith('/dev/dm-'):
            # No parent: the source is itself a whole disk.
            disks.add(source)

    _cache['system_disks'] = frozenset(disks)
    return _cache['system_disks']


# Names anaconda's first/primary disk usually takes. Only consulted when the
# OS disk could not be determined from live mounts.
_LIKELY_FIRST_DISKS = ('vda', 'sda', 'nvme0n1', 'xvda', 'hda')


def is_system_disk(device):
    """True if this disk (or a partition of it) holds the OS."""
    if not device:
        return True
    device = device.strip()
    disks = system_disks()

    if not disks:
        # Nothing could be probed (no lsblk, not root, odd container). Fall
        # back to the old name heuristic rather than declaring every disk
        # fair game — over-protecting costs a practice disk, under-
        # protecting costs the candidate's VM.
        return any(name in device for name in _LIKELY_FIRST_DISKS)

    if device in disks:
        return True
    parent = _parent_disk(device)
    return bool(parent and parent in disks)


# ── boot layout ─────────────────────────────────────────────────────────────

def efi_grub_configs():
    """Every /boot/efi/EFI/<vendor>/grub.cfg present.

    The vendor directory is distro-specific (redhat, rocky, almalinux,
    centos), so it's globbed rather than guessed one name at a time.
    """
    return sorted(glob.glob('/boot/efi/EFI/*/grub.cfg'))


def grub_config_present():
    """True if a usable GRUB config exists (BIOS or UEFI layout)."""
    return os.path.isfile('/boot/grub2/grub.cfg') or bool(efi_grub_configs())


# ── environment report ──────────────────────────────────────────────────────

def check_environment():
    """Report on how well this box suits the simulator.

    Returns a list of (level, message) where level is 'ok', 'warn' or
    'error'. Purely informational — nothing here blocks a session.
    """
    findings = []

    name = distro_name()
    did = distro_id()
    major = distro_major()

    if not did:
        findings.append(('warn',
                         "Could not read /etc/os-release — unable to confirm this "
                         "is a RHEL-family system. Tasks may not behave as expected."))
    elif did not in SUPPORTED_IDS and not is_rhel_family():
        findings.append(('error',
                         "%s is not a RHEL-family distribution. Package names, "
                         "SELinux, firewalld and boot layout will all differ; "
                         "most tasks will not grade correctly." % name))
    elif major is not None and major not in SUPPORTED_MAJORS:
        findings.append(('warn',
                         "%s — EX200 v10 targets major version 10 (9 is usable). "
                         "Some tasks may assume a different layout." % name))
    else:
        findings.append(('ok', "Detected %s" % name))

    detected = detected_system_vgs()
    if detected:
        findings.append(('ok', "Protected system volume group(s): %s"
                         % ', '.join(sorted(detected))))
    elif _run(['vgs', '--noheadings', '-o', 'vg_name'], timeout=5) is not None:
        findings.append(('ok', "No LVM-backed system mounts — nothing to protect"))
    else:
        findings.append(('warn',
                         "Could not probe LVM to identify this system's own volume "
                         "groups (lvm2 missing, or not running as root). Falling "
                         "back to a list of known names; storage tasks will be "
                         "conservative about which volumes they use."))

    if not grub_config_present():
        findings.append(('warn',
                         "No GRUB config found at /boot/grub2/grub.cfg or "
                         "/boot/efi/EFI/*/grub.cfg — boot tasks may not grade."))

    return findings


def describe():
    """One-line summary of the detected environment."""
    parts = [distro_name()]
    vgs = sorted(detected_system_vgs())
    if vgs:
        parts.append("system VG: %s" % ', '.join(vgs))
    return ' | '.join(parts)
