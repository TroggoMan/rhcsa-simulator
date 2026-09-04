"""
Regression test for issue #100: fault_sshd_config_001 (and the sibling
fault_fstab_001 check) reported the injected fault as still present even
after the candidate correctly removed it.

Root cause: `grep -c PATTERN FILE` exits 1 (non-zero) when the match count
is 0 — that's a real "no match" result, not a command failure. The
validators required `r.success` (returncode == 0) *and* `stdout == '0'`,
so the success-required branch could never be reached once the candidate
actually fixed the fault. Fixed by checking `stdout` alone, since
execute_safe() always captures stdout regardless of returncode.
"""

from types import SimpleNamespace

import pytest

from tasks import troubleshooting as ts

pytestmark = pytest.mark.unit


class FakeExecutor:
    """Emulates real command exit-code behavior relevant to these checks."""

    def __init__(self):
        self.sshd_config_has_bad_line = False
        self.fstab_has_bad_line = False

    def __call__(self, command, timeout=None):
        prog = command[0]

        if prog == 'sshd':
            return self._result(0, '')

        if prog == 'grep' and command[1] == '-c':
            pattern, path = command[2], command[3]
            if pattern == 'InvalidDirective':
                count = 1 if self.sshd_config_has_bad_line else 0
            elif pattern == 'RHCSA-FAULT-FSTAB':
                count = 1 if self.fstab_has_bad_line else 0
            else:
                count = 0
            # Real grep -c: exit 0 when count > 0, exit 1 when count == 0
            return self._result(0 if count else 1, str(count))

        if prog == 'systemctl' and command[1] == 'is-active':
            return self._result(0, 'active')

        if prog == 'mount' and command[1] == '-a':
            return self._result(0, '')

        return self._result(0, '')

    @staticmethod
    def _result(returncode, stdout):
        return SimpleNamespace(returncode=returncode, stdout=stdout, stderr='',
                                success=(returncode == 0))


@pytest.fixture
def fake_executor(monkeypatch):
    fake = FakeExecutor()
    monkeypatch.setattr(ts, 'execute_safe', fake)
    return fake


class TestSshdBadConfigFaultValidate:
    def test_passes_bad_line_check_once_directive_removed(self, fake_executor):
        fake_executor.sshd_config_has_bad_line = False
        task = ts.SshdBadConfigFaultTask()

        result = task.validate()

        bad_line_check = next(c for c in result.checks if c.name == 'bad_line_removed')
        assert bad_line_check.passed, bad_line_check.message
        assert bad_line_check.points == 3

    def test_still_fails_while_directive_present(self, fake_executor):
        fake_executor.sshd_config_has_bad_line = True
        task = ts.SshdBadConfigFaultTask()

        result = task.validate()

        bad_line_check = next(c for c in result.checks if c.name == 'bad_line_removed')
        assert not bad_line_check.passed


class TestBadFstabFaultValidate:
    def test_passes_bad_entry_check_once_entry_removed(self, fake_executor):
        fake_executor.fstab_has_bad_line = False
        task = ts.BadFstabFaultTask()

        result = task.validate()

        bad_entry_check = next(c for c in result.checks if c.name == 'bad_entry_removed')
        assert bad_entry_check.passed, bad_entry_check.message
        assert bad_entry_check.points == 5

    def test_still_fails_while_entry_present(self, fake_executor):
        fake_executor.fstab_has_bad_line = True
        task = ts.BadFstabFaultTask()

        result = task.validate()

        bad_entry_check = next(c for c in result.checks if c.name == 'bad_entry_removed')
        assert not bad_entry_check.passed
