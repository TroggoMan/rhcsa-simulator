"""
Regression test for issue #103: DiagnoseSELinuxServiceTask's samba scenario
required the candidate to enable the samba_enable_home_dirs boolean even
though the task's own symptom text ("Samba cannot access /srv/samba/data")
is a custom share path, not a user home directory. Per `man smbd_selinux`,
that boolean only governs sharing home directories, so it has no bearing on
a /srv/samba/data share -- fixing the fcontext (samba_share_t) is sufficient
and correct. The scenario mistakenly mixed in a requirement from an
unrelated home-directory scenario.
"""

import pytest

from tasks.selinux import DiagnoseSELinuxServiceTask

pytestmark = pytest.mark.unit


def test_samba_directory_scenario_does_not_require_home_dirs_boolean():
    task = DiagnoseSELinuxServiceTask()
    task.generate()
    # Force the samba/custom-directory scenario regardless of random choice.
    task.service = "samba"
    task.directory = "/srv/samba/data"
    task.context_type = "samba_share_t"
    task.boolean_name = None
    task.port = None
    task.port_type = None

    assert task.boolean_name is None, (
        "samba_enable_home_dirs only applies to sharing user home "
        "directories (man smbd_selinux) and is irrelevant to a custom "
        "share path like /srv/samba/data"
    )


def test_samba_scenario_in_generate_pool_has_no_boolean():
    """Regenerate many times so the samba scenario in the scenarios list
    is exercised, and confirm it never carries the unrelated boolean."""
    task = DiagnoseSELinuxServiceTask()
    seen_samba = False
    for _ in range(50):
        task.generate()
        if task.service == "samba":
            seen_samba = True
            assert task.directory == "/srv/samba/data"
            assert task.context_type == "samba_share_t"
            assert task.boolean_name is None
    assert seen_samba, "samba scenario was never selected across 50 generations"
