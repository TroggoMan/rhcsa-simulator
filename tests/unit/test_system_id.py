"""
Tests for utils.system_id — the distro/system-resource identification that
decides what belongs to the operating system and is therefore off-limits.

The regression that motivated this module: AlmaLinux names its root volume
group 'almalinux', which was absent from the hardcoded system-VG list, so the
simulator treated the box's own root VG as spare practice storage.
"""

import pytest

from utils import system_id


@pytest.fixture(autouse=True)
def _clear_cache():
    system_id.reset_cache()
    yield
    system_id.reset_cache()


def _fake_os_release(monkeypatch, content):
    monkeypatch.setattr(system_id, '_cache', {'os_release': content})


# ── os-release parsing ──────────────────────────────────────────────────────

def test_os_release_parses_quoted_values(monkeypatch, tmp_path):
    release = tmp_path / "os-release"
    release.write_text(
        'NAME="AlmaLinux"\n'
        'VERSION="10.0 (Purple Lion)"\n'
        'ID="almalinux"\n'
        'ID_LIKE="rhel centos fedora"\n'
        'VERSION_ID="10.0"\n'
        'PRETTY_NAME="AlmaLinux 10.0 (Purple Lion)"\n'
        '\n'
        '# a comment\n'
    )
    monkeypatch.setattr(system_id, 'OS_RELEASE_PATHS', (str(release),))

    assert system_id.distro_id() == 'almalinux'
    assert system_id.distro_version() == '10.0'
    assert system_id.distro_major() == 10
    assert system_id.distro_name() == 'AlmaLinux 10.0 (Purple Lion)'
    assert system_id.is_rhel_family() is True


def test_os_release_missing_is_not_fatal(monkeypatch):
    monkeypatch.setattr(system_id, 'OS_RELEASE_PATHS', ('/nonexistent/os-release',))
    assert system_id.os_release() == {}
    assert system_id.distro_id() == ''
    assert system_id.distro_major() is None


def test_non_rhel_family_detected(monkeypatch):
    _fake_os_release(monkeypatch, {'ID': 'ubuntu', 'ID_LIKE': 'debian',
                                   'VERSION_ID': '24.04',
                                   'PRETTY_NAME': 'Ubuntu 24.04 LTS'})
    assert system_id.is_rhel_family() is False


# ── system VG detection ─────────────────────────────────────────────────────

def test_almalinux_root_vg_is_protected(monkeypatch):
    """The exact bug: 'almalinux' is not in the legacy name list, so it has to
    be caught by probing the mounts."""
    monkeypatch.setattr(system_id, 'detected_system_vgs',
                        lambda: {'almalinux'})
    monkeypatch.setattr(system_id, '_distro_vg_guesses', lambda: set())

    assert system_id.is_system_vg('almalinux') is True
    assert system_id.is_system_vg('vg_practice') is False


def test_detected_vgs_come_from_mounts_and_swap(monkeypatch):
    sources = {'/': '/dev/mapper/almalinux-root',
               '/home': '/dev/mapper/almalinux-home'}
    monkeypatch.setattr(system_id, '_source_of_mountpoint',
                        lambda mp: sources.get(mp))
    monkeypatch.setattr(system_id, '_active_swap_devices',
                        lambda: ['/dev/dm-1'])

    def fake_vg_of_device(dev):
        return {'/dev/mapper/almalinux-root': 'almalinux',
                '/dev/mapper/almalinux-home': 'almalinux',
                '/dev/dm-1': 'almalinux'}.get(dev)

    monkeypatch.setattr(system_id, 'vg_of_device', fake_vg_of_device)
    monkeypatch.setattr(system_id.os.path, 'exists', lambda p: True)

    assert system_id.detected_system_vgs() == {'almalinux'}


def test_known_names_still_protected_when_probe_fails(monkeypatch):
    """An unprobeable box keeps the old (partial) protection rather than none."""
    monkeypatch.setattr(system_id, 'detected_system_vgs', lambda: set())
    monkeypatch.setattr(system_id, '_distro_vg_guesses', lambda: set())

    for name in ('rl', 'rhel', 'centos', 'almalinux', 'rocky'):
        assert system_id.is_system_vg(name) is True, name
    assert system_id.is_system_vg('vg_exam1') is False


def test_unknown_distro_root_vg_guessed_from_os_release(monkeypatch):
    """A distro nobody thought of still gets its likely root VG protected."""
    _fake_os_release(monkeypatch, {'ID': 'navylinux', 'VERSION_ID': '10.1'})
    monkeypatch.setattr(system_id, 'detected_system_vgs', lambda: set())

    assert system_id.is_system_vg('navylinux') is True
    assert system_id.is_system_vg('navylinux10') is True
    assert system_id.is_system_vg('vg_exam1') is False


def test_blank_vg_name_treated_as_system(monkeypatch):
    """Refusing to touch what we can't identify is the safe default when the
    alternative is lvremove."""
    monkeypatch.setattr(system_id, 'detected_system_vgs', lambda: set())
    assert system_id.is_system_vg('') is True
    assert system_id.is_system_vg(None) is True
    assert system_id.is_system_vg('   ') is True


def test_vg_of_device_returns_none_for_non_lv(monkeypatch):
    monkeypatch.setattr(system_id, '_run', lambda cmd, timeout=10: None)
    assert system_id.vg_of_device('/dev/sdb') is None
    assert system_id.vg_of_device('') is None
    assert system_id.vg_of_device('not-a-device') is None


# ── system disk detection ───────────────────────────────────────────────────

def test_system_disk_detected_from_pvs_not_from_name(monkeypatch):
    monkeypatch.setattr(system_id, 'system_pvs', lambda: frozenset({'/dev/vdb2'}))
    monkeypatch.setattr(system_id, '_source_of_mountpoint',
                        lambda mp: '/dev/mapper/almalinux-root' if mp == '/' else None)
    monkeypatch.setattr(system_id, '_parent_disk',
                        lambda dev: '/dev/vdb' if dev == '/dev/vdb2' else None)

    assert system_id.system_disks() == frozenset({'/dev/vdb'})
    # The OS is on the *second* disk here; the first is fair game.
    assert system_id.is_system_disk('/dev/vdb') is True
    assert system_id.is_system_disk('/dev/vda') is False


def test_system_disk_falls_back_to_name_when_unprobeable(monkeypatch):
    monkeypatch.setattr(system_id, 'system_disks', lambda: frozenset())
    assert system_id.is_system_disk('/dev/sda') is True
    assert system_id.is_system_disk('/dev/nvme0n1') is True
    assert system_id.is_system_disk('/dev/sdd') is False


def test_empty_device_is_treated_as_system(monkeypatch):
    assert system_id.is_system_disk('') is True
    assert system_id.is_system_disk(None) is True


# ── boot layout ─────────────────────────────────────────────────────────────

def test_efi_grub_config_globs_any_vendor_dir(monkeypatch):
    monkeypatch.setattr(system_id.glob, 'glob',
                        lambda pat: ['/boot/efi/EFI/almalinux/grub.cfg'])
    monkeypatch.setattr(system_id.os.path, 'isfile', lambda p: False)

    assert system_id.efi_grub_configs() == ['/boot/efi/EFI/almalinux/grub.cfg']
    assert system_id.grub_config_present() is True


def test_grub_absent_reported(monkeypatch):
    monkeypatch.setattr(system_id.glob, 'glob', lambda pat: [])
    monkeypatch.setattr(system_id.os.path, 'isfile', lambda p: False)
    assert system_id.grub_config_present() is False


# ── environment report ──────────────────────────────────────────────────────

def test_check_environment_flags_non_rhel(monkeypatch):
    _fake_os_release(monkeypatch, {'ID': 'ubuntu', 'ID_LIKE': 'debian',
                                   'VERSION_ID': '24.04',
                                   'PRETTY_NAME': 'Ubuntu 24.04 LTS'})
    monkeypatch.setattr(system_id, 'detected_system_vgs', lambda: set())
    monkeypatch.setattr(system_id, '_run', lambda cmd, timeout=10: None)
    monkeypatch.setattr(system_id, 'grub_config_present', lambda: True)

    levels = [level for level, _ in system_id.check_environment()]
    assert 'error' in levels


def test_check_environment_accepts_almalinux_10(monkeypatch):
    _fake_os_release(monkeypatch, {'ID': 'almalinux', 'ID_LIKE': 'rhel centos fedora',
                                   'VERSION_ID': '10.0',
                                   'PRETTY_NAME': 'AlmaLinux 10.0'})
    monkeypatch.setattr(system_id, 'detected_system_vgs', lambda: {'almalinux'})
    monkeypatch.setattr(system_id, 'grub_config_present', lambda: True)

    findings = system_id.check_environment()
    assert all(level == 'ok' for level, _ in findings), findings
    assert any('AlmaLinux' in msg for _, msg in findings)


def test_check_environment_warns_on_unsupported_major(monkeypatch):
    _fake_os_release(monkeypatch, {'ID': 'rocky', 'ID_LIKE': 'rhel centos fedora',
                                   'VERSION_ID': '8.10',
                                   'PRETTY_NAME': 'Rocky Linux 8.10'})
    monkeypatch.setattr(system_id, 'detected_system_vgs', lambda: {'rl'})
    monkeypatch.setattr(system_id, 'grub_config_present', lambda: True)

    levels = [level for level, _ in system_id.check_environment()]
    assert 'warn' in levels


def test_probes_never_raise(monkeypatch):
    """Every probe goes through _run, which must swallow a missing binary,
    a timeout and a non-zero exit rather than raise into a validator."""
    import subprocess

    def missing(*a, **kw):
        raise FileNotFoundError("lvs")

    monkeypatch.setattr(system_id.subprocess, 'run', missing)
    assert system_id._run(['lvs']) is None

    def timeout(*a, **kw):
        raise subprocess.TimeoutExpired(cmd='lvs', timeout=5)

    monkeypatch.setattr(system_id.subprocess, 'run', timeout)
    assert system_id._run(['lvs']) is None

    class Failed:
        returncode = 5
        stdout = 'partial'

    monkeypatch.setattr(system_id.subprocess, 'run', lambda *a, **kw: Failed())
    assert system_id._run(['lvs']) is None
