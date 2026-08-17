"""ConfigureChronydTask: the offered NTP server must be one the candidate can
actually sync against.

RFC 2606 reserved domains (example.com/.org/.net) never resolve to a real
server, so a task that tells the candidate to add one to /etc/chrony.conf and
then "verify synchronization" sets up a check that can never pass for real
(issue #92). Real servers are used instead, matching the precedent in
tasks/repos.py and ConfigureNTPPoolTask.
"""

from tasks.time_services import ConfigureChronydTask

RESERVED_EXAMPLE_DOMAINS = ('.example.com', '.example.org', '.example.net',
                            'example.com', 'example.org', 'example.net')


class TestConfigureChronydTaskServerPool:
    def test_default_pool_has_no_reserved_example_domains(self):
        for _ in range(50):
            task = ConfigureChronydTask().generate()
            assert not task.ntp_server.endswith(RESERVED_EXAMPLE_DOMAINS), (
                f"{task.ntp_server} is an RFC 2606 reserved domain and can "
                "never actually synchronize"
            )

    def test_explicit_server_param_is_still_honored(self):
        task = ConfigureChronydTask().generate(server='custom.ntp.host')
        assert task.ntp_server == 'custom.ntp.host'
