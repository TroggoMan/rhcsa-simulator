"""
Local (single-machine) NFS server provisioning, added for issue #91.

The original fix for #91 hid NFS/autofs tasks until a *remote* server was
configured over SSH — but not every candidate has a second machine to
provision as one. This adds a local mode that provisions THIS machine as its
own NFS server (loopback), so the tasks are completable with just one box.
These tests cover the dispatch between local and remote modes without
actually touching the network or the filesystem.
"""

from types import SimpleNamespace

import pytest

from core import nfs_server

pytestmark = pytest.mark.unit


def _fake_run(returncode=0, stdout='', stderr=''):
    def run(*args, **kwargs):
        return SimpleNamespace(returncode=returncode, stdout=stdout, stderr=stderr)
    return run


class TestProvisionLocal:
    def test_provision_local_runs_bash_directly_no_ssh(self, monkeypatch):
        captured = {}

        def fake_run(cmd, input=None, text=None, capture_output=None, timeout=None):
            captured['cmd'] = cmd
            out = (f"== active exports ==\n"
                   f"{nfs_server._EXPORTS_LINE}'/exports/rhcsa/data'\n"
                   f"{nfs_server._DONE}\n")
            return SimpleNamespace(returncode=0, stdout=out, stderr='')

        monkeypatch.setattr(nfs_server.subprocess, 'run', fake_run)
        ok, exports, output = nfs_server.provision_local()

        assert ok is True
        assert exports == ['/exports/rhcsa/data']
        assert captured['cmd'] == ['bash', '-s']

    def test_provision_local_failure_is_reported(self, monkeypatch):
        out = f"{nfs_server._FAIL} could not install nfs-utils\n"
        monkeypatch.setattr(nfs_server.subprocess, 'run', _fake_run(returncode=1, stdout=out))
        ok, exports, output = nfs_server.provision_local()

        assert ok is False
        assert exports == []
        assert 'could not install nfs-utils' in output


class TestSaveConfigLocalFlag:
    def test_save_config_local_marks_config_and_omits_password(self, tmp_path, monkeypatch):
        monkeypatch.setattr(nfs_server, 'STATE_DIR', str(tmp_path))
        monkeypatch.setattr(nfs_server, 'CONFIG_PATH', str(tmp_path / 'nfs_server.conf'))

        cfg = nfs_server.save_config(nfs_server.LOCAL_HOST, None,
                                     ['/exports/rhcsa/data'], local=True)

        assert cfg['local'] is True
        assert cfg['host'] == 'localhost'
        assert 'password' not in cfg
        assert nfs_server.load_config() == cfg

    def test_save_config_remote_has_no_local_flag(self, tmp_path, monkeypatch):
        monkeypatch.setattr(nfs_server, 'STATE_DIR', str(tmp_path))
        monkeypatch.setattr(nfs_server, 'CONFIG_PATH', str(tmp_path / 'nfs_server.conf'))

        cfg = nfs_server.save_config('nfs1.lab.example.com', 'root', ['/exports/rhcsa/data'])

        assert 'local' not in cfg


class TestReprovisionDispatch:
    def test_reprovision_local_config_calls_provision_local_not_ssh(self, monkeypatch):
        monkeypatch.setattr(nfs_server, 'load_config',
                            lambda: {'host': 'localhost', 'local': True,
                                     'exports': ['/exports/rhcsa/data']})

        called = {}
        def fake_provision_local():
            called['yes'] = True
            return True, ['/exports/rhcsa/data'], 'ok'
        monkeypatch.setattr(nfs_server, 'provision_local', fake_provision_local)

        def fail_if_called(*a, **k):
            raise AssertionError('remote provision() should not be called for a local config')
        monkeypatch.setattr(nfs_server, 'provision', fail_if_called)

        ok, exports, out = nfs_server.reprovision_from_config()
        assert ok is True
        assert called.get('yes') is True
        assert exports == ['/exports/rhcsa/data']

    def test_reprovision_remote_config_calls_remote_provision(self, monkeypatch):
        monkeypatch.setattr(nfs_server, 'load_config',
                            lambda: {'host': 'nfs1.lab.example.com', 'user': 'root',
                                     'exports': ['/exports/rhcsa/data']})

        called = {}
        def fake_provision(host, user, password=None, batch=False):
            called['args'] = (host, user)
            return True, ['/exports/rhcsa/data'], 'ok'
        monkeypatch.setattr(nfs_server, 'provision', fake_provision)

        ok, exports, out = nfs_server.reprovision_from_config()
        assert ok is True
        assert called['args'] == ('nfs1.lab.example.com', 'root')

    def test_reprovision_no_config_reports_unusable(self, monkeypatch):
        monkeypatch.setattr(nfs_server, 'load_config', lambda: None)
        ok, exports, reason = nfs_server.reprovision_from_config()
        assert ok is None and exports is None
        assert 'no NFS server configured' in reason


class TestRemoveExportsDispatch:
    def test_remove_exports_local_config_skips_ssh(self, monkeypatch):
        monkeypatch.setattr(nfs_server, 'load_config',
                            lambda: {'host': 'localhost', 'local': True,
                                     'exports': ['/exports/rhcsa/data']})

        called = {}
        def fake_remove_local():
            called['yes'] = True
            return True, 'ok'
        monkeypatch.setattr(nfs_server, 'remove_local_exports', fake_remove_local)

        def fail_if_called(*a, **k):
            raise AssertionError('_run_remote should not be called for a local config')
        monkeypatch.setattr(nfs_server, '_run_remote', fail_if_called)

        ok, out = nfs_server.remove_exports()
        assert ok is True
        assert called.get('yes') is True

    def test_remove_exports_remote_config_uses_ssh(self, monkeypatch):
        monkeypatch.setattr(nfs_server, 'load_config',
                            lambda: {'host': 'nfs1.lab.example.com', 'user': 'root',
                                     'exports': ['/exports/rhcsa/data']})

        called = {}
        def fake_run_remote(script, host, user, password=None, batch=False, timeout=600):
            called['host'] = host
            return 0, nfs_server._DONE
        monkeypatch.setattr(nfs_server, '_run_remote', fake_run_remote)

        ok, out = nfs_server.remove_exports()
        assert ok is True
        assert called['host'] == 'nfs1.lab.example.com'
