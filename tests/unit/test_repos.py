"""
Tests for GitHub issue #101: ConfigureRepoTask (repo_configure_001)
false-failed the baseurl and gpgcheck checks when the candidate wrote the
.repo file with whitespace around "=" (e.g. "baseurl = <url>"), which is
valid INI syntax that dnf's own configparser-based reader accepts fine.
"""

import subprocess
import tempfile
from unittest.mock import patch

import pytest

from tasks.repos import ConfigureRepoTask
from validators.safe_executor import ExecutionResult


pytestmark = pytest.mark.unit


def _fake_execute_safe(repo_file, real_path):
    """Run the real grep/test commands against a temp file standing in for
    the repo file path the task hardcodes."""

    def _exec(cmd):
        cmd = [real_path if part == repo_file else part for part in cmd]
        result = subprocess.run(cmd, capture_output=True, text=True)
        return ExecutionResult(
            returncode=result.returncode,
            stdout=result.stdout,
            stderr=result.stderr,
            success=result.returncode == 0,
        )

    return _exec


def _task():
    return ConfigureRepoTask().generate(
        config={
            'repo_id': 'google-cloud-cli',
            'repo_name': 'Google Cloud CLI',
            'base_url': 'https://packages.cloud.google.com/yum/repos/cloud-sdk-el9-x86_64/',
            'gpg_key_url': None,
        },
        gpgcheck=0,
    )


class TestConfigureRepoTaskWhitespace:
    """dnf parses .repo files as INI, which allows optional whitespace
    around "=". The validator must accept that, not just "key=value"."""

    def _validate_with_content(self, content):
        task = _task()
        repo_file = f'/etc/yum.repos.d/{task.repo_id}.repo'
        with tempfile.NamedTemporaryFile('w', suffix='.repo', delete=False) as f:
            f.write(content)
            real_path = f.name
        try:
            with patch('tasks.repos.execute_safe', _fake_execute_safe(repo_file, real_path)):
                return task.validate()
        finally:
            import os
            os.unlink(real_path)

    def test_spaces_around_equals_pass(self):
        content = (
            "[google-cloud-cli]\n"
            "name = Google Cloud CLI\n"
            "baseurl = https://packages.cloud.google.com/yum/repos/cloud-sdk-el9-x86_64/\n"
            "enabled = 1\n"
            "gpgcheck = 0\n"
        )
        result = self._validate_with_content(content)
        by_name = {c.name: c for c in result.checks}
        assert by_name['baseurl_configured'].passed
        assert by_name['gpgcheck_setting'].passed
        assert result.passed

    def test_no_spaces_around_equals_still_passes(self):
        content = (
            "[google-cloud-cli]\n"
            "name=Google Cloud CLI\n"
            "baseurl=https://packages.cloud.google.com/yum/repos/cloud-sdk-el9-x86_64/\n"
            "enabled=1\n"
            "gpgcheck=0\n"
        )
        result = self._validate_with_content(content)
        by_name = {c.name: c for c in result.checks}
        assert by_name['baseurl_configured'].passed
        assert by_name['gpgcheck_setting'].passed
        assert result.passed

    def test_wrong_baseurl_still_fails(self):
        content = (
            "[google-cloud-cli]\n"
            "name = Google Cloud CLI\n"
            "baseurl = https://example.com/wrong/\n"
            "enabled = 1\n"
            "gpgcheck = 0\n"
        )
        result = self._validate_with_content(content)
        by_name = {c.name: c for c in result.checks}
        assert not by_name['baseurl_configured'].passed
        assert by_name['baseurl_configured'].points == 1
