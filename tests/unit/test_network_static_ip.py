"""
Tests for GitHub issue #93: ConfigureStaticIPTask (net_static_ip_001)
false-failed the gateway and interface-up checks on the dummy0 practice
interface even when the candidate configured it correctly.

Root causes:
  * get_interface_state() only recognized 'state UP'/'state DOWN'. Virtual
    interfaces like dummy0 report 'state UNKNOWN' even when administratively
    up, so the check always returned None.
  * The gateway check read the box's active default route (`ip route show
    default`), but dummy0 is created with ipv4.never-default so it can never
    become the real default route without breaking the candidate's live
    connectivity - the profile's configured gateway must be checked instead.
"""

from unittest.mock import patch

import pytest

from tasks.networking import ConfigureStaticIPTask
from validators.safe_executor import ExecutionResult
from validators.system_validators import get_interface_state


pytestmark = pytest.mark.unit


def _result(stdout, success=True):
    return ExecutionResult(returncode=0 if success else 1, stdout=stdout, stderr="", success=success)


class TestGetInterfaceStateVirtual:
    """Dummy/loopback-style interfaces report operstate UNKNOWN, not UP/DOWN."""

    def test_unknown_state_with_lower_up_is_treated_as_up(self):
        stdout = (
            "3: dummy0: <BROADCAST,NOARP,UP,LOWER_UP> mtu 1500 qdisc noqueue "
            "state UNKNOWN mode DEFAULT group default qlen 1000\n"
            "    link/ether 12:34:56:78:9a:bc brd ff:ff:ff:ff:ff:ff"
        )
        with patch("validators.system_validators.execute_safe", return_value=_result(stdout)):
            assert get_interface_state("dummy0") == "UP"

    def test_unknown_state_without_lower_up_is_down(self):
        stdout = (
            "3: dummy0: <BROADCAST,NOARP> mtu 1500 qdisc noop "
            "state UNKNOWN mode DEFAULT group default qlen 1000\n"
            "    link/ether 12:34:56:78:9a:bc brd ff:ff:ff:ff:ff:ff"
        )
        with patch("validators.system_validators.execute_safe", return_value=_result(stdout)):
            assert get_interface_state("dummy0") == "DOWN"

    def test_real_state_up_still_recognized(self):
        stdout = (
            "2: eth0: <BROADCAST,MULTICAST,UP,LOWER_UP> mtu 1500 qdisc fq_codel "
            "state UP mode DEFAULT group default qlen 1000"
        )
        with patch("validators.system_validators.execute_safe", return_value=_result(stdout)):
            assert get_interface_state("eth0") == "UP"

    def test_command_failure_returns_none(self):
        with patch("validators.system_validators.execute_safe", return_value=_result("", success=False)):
            assert get_interface_state("dummy0") is None


def _nmcli_info(gateway, method="manual"):
    return {"ipv4.gateway": gateway, "ipv4.method": method}


class TestConfigureStaticIPGateway:
    """Gateway must be graded from the saved connection profile, not the
    live routing table, since the practice interface is never-default."""

    def _task(self):
        task = ConfigureStaticIPTask().generate(
            interface="dummy0",
            ip="192.168.212.131",
            prefix="24",
            gateway="192.168.212.1",
            dns="1.1.1.1",
            connection="dummy0",
        )
        return task

    def test_passes_when_profile_gateway_matches_despite_different_active_route(self):
        task = self._task()
        with patch("tasks.networking.get_ip_address", return_value="192.168.212.131"), \
             patch("tasks.networking.get_interface_state", return_value="UP"), \
             patch("tasks.networking.get_dns_servers", return_value=["1.1.1.1"]), \
             patch("tasks.networking.get_nmcli_connection_info",
                   return_value=_nmcli_info("192.168.212.1")), \
             patch("tasks.networking.get_default_gateway", return_value="192.168.30.1"):
            result = task.validate()

        gateway_check = next(c for c in result.checks if c.name == "gateway_set")
        assert gateway_check.passed is True
        assert gateway_check.points == 3
        assert result.passed is True
        assert result.score == task.points

    def test_fails_when_profile_gateway_does_not_match(self):
        task = self._task()
        with patch("tasks.networking.get_ip_address", return_value="192.168.212.131"), \
             patch("tasks.networking.get_interface_state", return_value="UP"), \
             patch("tasks.networking.get_dns_servers", return_value=["1.1.1.1"]), \
             patch("tasks.networking.get_nmcli_connection_info",
                   return_value=_nmcli_info("10.0.0.1")), \
             patch("tasks.networking.get_default_gateway", return_value=None):
            result = task.validate()

        gateway_check = next(c for c in result.checks if c.name == "gateway_set")
        assert gateway_check.passed is False
