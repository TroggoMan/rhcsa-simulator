"""
Tests for EX200 v9 / v10 mode.

The two exams are not the same syllabus, and the difference is asymmetric:

    v9 only   Manage containers, MBR partition tables
    v10 only  Flatpak, systemd timer units

Drawing an out-of-scope task means grading a candidate against objectives
their exam does not contain, so the filtering is the part that matters most
here.
"""

import pytest

from config import settings
from config.exam_objectives import get_objectives, get_domain_name
from tasks.registry import TaskRegistry


@pytest.fixture(autouse=True)
def _restore_version():
    original = settings.get_exam_version()
    yield
    settings.set_exam_version(original)


@pytest.fixture(scope='module', autouse=True)
def _registry():
    TaskRegistry.initialize()


# ── version switching ───────────────────────────────────────────────────────

def test_default_is_the_current_exam():
    assert settings.DEFAULT_EXAM_VERSION == 10


def test_set_and_get_round_trip():
    settings.set_exam_version(9)
    assert settings.get_exam_version() == 9
    settings.set_exam_version(10)
    assert settings.get_exam_version() == 10


def test_string_version_accepted():
    """--exam-version comes off a CLI, so '9' must work as well as 9."""
    settings.set_exam_version('9')
    assert settings.get_exam_version() == 9


@pytest.mark.parametrize('bad', [8, 11, 0, -1, 'eleven'])
def test_unsupported_version_rejected(bad):
    """Falling back silently would grade against the wrong syllabus."""
    with pytest.raises((ValueError, TypeError)):
        settings.set_exam_version(bad)


# ── category scope ──────────────────────────────────────────────────────────

@pytest.mark.parametrize('category,in_v9,in_v10', [
    ('containers', True, False),      # dropped in v10
    ('flatpak', False, True),         # introduced in v10
    ('systemd_timers', False, True),  # v9 scheduling is at/cron only
    ('lvm', True, True),
    ('selinux', True, True),
])
def test_category_scope_per_version(category, in_v9, in_v10):
    assert settings.category_in_scope(category, 9) is in_v9
    assert settings.category_in_scope(category, 10) is in_v10


def test_registry_reports_only_in_scope_categories():
    settings.set_exam_version(9)
    v9 = set(TaskRegistry.categories_in_scope())
    settings.set_exam_version(10)
    v10 = set(TaskRegistry.categories_in_scope())

    assert 'containers' in v9 and 'containers' not in v10
    assert 'flatpak' in v10 and 'flatpak' not in v9
    assert 'systemd_timers' in v10 and 'systemd_timers' not in v9


def test_out_of_scope_category_yields_no_task():
    settings.set_exam_version(10)
    assert TaskRegistry.get_random_task(category='containers') is None
    settings.set_exam_version(9)
    assert TaskRegistry.get_random_task(category='flatpak') is None


# ── task-level scope (MBR) ──────────────────────────────────────────────────

def test_mbr_partitioning_is_v9_only():
    """v10's objective is "partitions on GPT disks" — MBR was dropped, so the
    task must not be drawn even though `partitioning` is in scope for both."""
    from tasks.partitioning import CreateMBRPartitionTask

    assert TaskRegistry.in_scope(CreateMBRPartitionTask, 9) is True
    assert TaskRegistry.in_scope(CreateMBRPartitionTask, 10) is False


def test_partitioning_category_stays_in_scope_for_both():
    assert settings.category_in_scope('partitioning', 9)
    assert settings.category_in_scope('partitioning', 10)


# ── domains and objectives ──────────────────────────────────────────────────

def test_containers_domain_exists_only_in_v9():
    assert 9 in settings.exam_domains(9)
    assert 9 not in settings.exam_domains(10)


def test_objectives_differ_by_version():
    v9, v10 = get_objectives(9), get_objectives(10)
    assert 9 in v9 and 9 not in v10
    assert get_domain_name(9, version=9) == 'Containers'


@pytest.mark.parametrize('version', [9, 10])
def test_weights_sum_to_100(version):
    """Domain weights drive exam composition; drift means a lopsided exam."""
    assert sum(d['weight'] for d in get_objectives(version).values()) == 100


def test_v9_objectives_carry_the_version_specific_bullets():
    text = ' '.join(
        obj for domain in get_objectives(9).values()
        for obj in domain['objectives']).lower()
    assert 'mbr' in text
    assert 'set-gid' in text
    assert 'skopeo' in text or 'podman' in text
    assert 'flatpak' not in text


def test_v10_objectives_carry_flatpak_and_not_containers():
    text = ' '.join(
        obj for domain in get_objectives(10).values()
        for obj in domain['objectives']).lower()
    assert 'flatpak' in text
    assert 'podman' not in text and 'skopeo' not in text


# ── generated exams ─────────────────────────────────────────────────────────

@pytest.mark.parametrize('version', [9, 10])
def test_generated_exam_never_leaks_out_of_scope_tasks(version):
    settings.set_exam_version(version)
    tasks = TaskRegistry.generate_exam(20, disk_budget=4)

    assert tasks, "no tasks generated"
    leaked = [t.category for t in tasks
              if not settings.category_in_scope(t.category, version)]
    assert not leaked, f"v{version} exam contained out-of-scope: {leaked}"


def test_v9_exam_can_include_containers():
    settings.set_exam_version(9)
    # Domain balancing is randomised; sample a few exams rather than assume
    # one draw covers domain 9.
    seen = set()
    for _ in range(3):
        seen.update(t.category for t in
                    TaskRegistry.generate_exam(20, disk_budget=4))
    assert 'containers' in seen


def test_v10_exam_never_includes_containers():
    settings.set_exam_version(10)
    seen = set()
    for _ in range(3):
        seen.update(t.category for t in
                    TaskRegistry.generate_exam(20, disk_budget=4))
    assert 'containers' not in seen


# ── preflight packages ──────────────────────────────────────────────────────

def test_podman_required_only_for_v9():
    from core import preflight

    assert 'podman' in preflight.required_packages(9)
    assert 'podman' not in preflight.required_packages(10)
    # Shared requirements survive in both.
    assert 'httpd' in preflight.required_packages(9)
    assert 'httpd' in preflight.required_packages(10)
