"""NFS/autofs tasks: registry gating on a configured real NFS server.

Without a real server configured, generate() falls back to an unreachable
placeholder host (e.g. server1.example.com) that can never actually be
mounted, so these tasks must not be handed out until Setup configures one.
"""

from core import nfs_server
from tasks.registry import TaskRegistry
from tasks.network_storage import (
    MountNFSShareTask,
    PersistentNFSMountTask,
    ConfigureAutofsTask,
    AutofsHomeDirectoriesTask,
)

NFS_TASK_CLASSES = (
    MountNFSShareTask,
    PersistentNFSMountTask,
    ConfigureAutofsTask,
    AutofsHomeDirectoriesTask,
)


class TestRegistryGating:
    def test_all_nfs_tasks_declare_the_flag(self):
        for cls in NFS_TASK_CLASSES:
            assert cls.requires_nfs_server is True

    def test_nfs_tasks_hidden_without_configured_server(self, monkeypatch):
        monkeypatch.setattr(nfs_server, 'load_config', lambda: None)
        monkeypatch.setitem(TaskRegistry._tasks, '_test_nfs_only',
                            [MountNFSShareTask])
        assert TaskRegistry.get_random_task(category='_test_nfs_only') is None

    def test_nfs_tasks_offered_when_server_configured(self, monkeypatch):
        monkeypatch.setattr(nfs_server, 'load_config', lambda: {
            'host': 'nfs1.lab.example.com', 'user': 'root',
            'exports': ['/exports/rhcsa/data'],
        })
        monkeypatch.setitem(TaskRegistry._tasks, '_test_nfs_only',
                            [MountNFSShareTask])
        task = TaskRegistry.get_random_task(category='_test_nfs_only')
        assert task is not None and task.id == 'nfs_mount_001'

    def test_mixed_category_falls_back_to_other_tasks(self, monkeypatch):
        """If a category mixes NFS and non-NFS tasks, only the NFS one is
        filtered out when no server is configured."""
        from tasks.time_services import ConfigureTimezoneTask

        monkeypatch.setattr(nfs_server, 'load_config', lambda: None)
        monkeypatch.setitem(TaskRegistry._tasks, '_test_mixed',
                            [MountNFSShareTask, ConfigureTimezoneTask])
        task = TaskRegistry.get_random_task(category='_test_mixed')
        assert task is not None and task.id != 'nfs_mount_001'


class TestGenerateUsesConfiguredServer(object):
    def test_generate_still_uses_placeholder_when_unreachable_dict(self, monkeypatch):
        """generate() itself is unchanged — it still falls back to the
        placeholder host if called directly without a config. Gating happens
        one level up, in the registry."""
        monkeypatch.setattr(nfs_server, 'load_config', lambda: None)
        t = MountNFSShareTask().generate()
        assert t.nfs_server == 'server1.example.com'
