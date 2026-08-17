"""
Network configuration tasks for RHCSA EX200 v10 exam.

Covers: static IP, DHCP, hostname, DNS, static routes, /etc/hosts,
connection creation, troubleshooting, bonding, IPv6, connectivity
verification, connection restart, network info display, search domains,
and full network setup.
"""

import random
import logging
from tasks.base import BaseTask
from tasks.registry import TaskRegistry
from core.validator import ValidationCheck, ValidationResult
from validators.safe_executor import execute_safe
from validators.system_validators import (
    get_ip_address, get_interface_state, validate_interface_ip,
    get_default_gateway, get_dns_servers, validate_dns_server,
    get_nmcli_connection_info
)
from validators.file_validators import validate_file_contains


logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helper utilities
# ---------------------------------------------------------------------------

# A dedicated, isolated dummy interface used by every task that *modifies*
# network settings. Reconfiguring the candidate's real/primary NIC (ens160,
# eth0, ...) would drop their live connection, so practice always happens on
# this throwaway interface instead.
PRACTICE_INTERFACE = 'dummy0'
PRACTICE_CONNECTION = 'dummy0'
# RFC 5737 documentation range — a harmless placeholder so the interface comes
# up with an address (tasks that assign a *specific* IP still have to change it).
_PRACTICE_BASE_IP = '192.0.2.10/24'


def _ensure_practice_interface():
    """
    Make sure the isolated 'dummy0' practice interface exists and is up.

    Idempotent and best-effort: on systems without root / iproute2 / NM the
    calls fail silently and the interface name is still returned so task
    generation never raises.
    """
    import subprocess

    def _run(cmd):
        try:
            return subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        except Exception:
            return None

    show = _run(['ip', 'link', 'show', PRACTICE_INTERFACE])
    if show is None or show.returncode != 0:
        _run(['ip', 'link', 'add', PRACTICE_INTERFACE, 'type', 'dummy'])
    _run(['ip', 'link', 'set', PRACTICE_INTERFACE, 'up'])

    # Bind a NetworkManager profile so nmcli con mod/up behaves like a real NIC.
    shown = _run(['nmcli', '-t', '-f', 'NAME', 'con', 'show'])
    names = shown.stdout.splitlines() if shown and shown.stdout else []
    if PRACTICE_CONNECTION not in names:
        _run(['nmcli', 'con', 'add', 'type', 'dummy',
              'con-name', PRACTICE_CONNECTION, 'ifname', PRACTICE_INTERFACE,
              'ipv4.method', 'manual', 'ipv4.addresses', _PRACTICE_BASE_IP,
              'ipv4.never-default', 'yes', 'ipv6.never-default', 'yes',
              'connection.autoconnect', 'no'])
        _run(['nmcli', 'con', 'up', PRACTICE_CONNECTION])
    return PRACTICE_INTERFACE


def _get_practice_interface():
    """
    Return an isolated dummy interface for practice tasks.

    IMPORTANT: this NEVER returns the primary/live interface. The previous
    implementation fell back to the primary NIC when no spare interface
    existed, which meant a static-IP task could clobber the candidate's live
    connection. A dedicated 'dummy0' interface is created on demand instead.
    """
    return _ensure_practice_interface()


def _get_primary_interface():
    """Get the primary network interface."""
    try:
        from device.network_manager import get_primary_interface
        iface = get_primary_interface()
        if iface:
            return iface
    except Exception:
        pass
    return 'eth0'


def _get_connection_name(interface):
    """Get connection name for an interface."""
    try:
        from device.network_manager import get_connection_for_interface
        conn = get_connection_for_interface(interface)
        if conn:
            return conn
    except Exception:
        pass
    return interface


def _random_subnet():
    """Return a random third-octet value for 192.168.x.0/24 ranges."""
    return random.randint(1, 254)


def _random_host():
    """Return a random host portion (10-250) for IP addresses."""
    return random.randint(10, 250)


def _random_interface():
    """Return a random realistic interface name."""
    return random.choice(['eth0', 'ens192', 'ens160', 'ens33', 'ens224'])


def _random_hostname():
    """Return a random realistic FQDN."""
    names = [
        'server1.example.com', 'server2.example.com',
        'node1.lab.example.com', 'node2.lab.example.com',
        'rhel10.lab.local', 'workstation.test.net',
        'app01.prod.example.com', 'db01.corp.example.com',
        'web01.example.com', 'mail.example.com',
    ]
    return random.choice(names)


def _random_dns_pair():
    """Return a random pair of DNS servers."""
    pairs = [
        ['8.8.8.8', '8.8.4.4'],
        ['1.1.1.1', '1.0.0.1'],
        ['9.9.9.9', '149.112.112.112'],
        ['208.67.222.222', '208.67.220.220'],
    ]
    return random.choice(pairs)


# ===================================================================
# 1. ConfigureStaticIPTask  (exam / 15 pts) [PERSIST]
# ===================================================================

@TaskRegistry.register("networking")
class ConfigureStaticIPTask(BaseTask):
    """Configure a static IP address with prefix, gateway, and DNS via nmcli."""

    def __init__(self):
        super().__init__(
            id="net_static_ip_001",
            category="networking",
            difficulty="exam",
            points=15
        )
        self.requires_persistence = True
        self.tags = ["nmcli", "static-ip", "ipv4", "persistence"]
        self.exam_tips = [
            "Always set ipv4.method to 'manual' when assigning a static IP.",
            "Remember to bring the connection up after modification.",
            "Use 'nmcli con show <name>' to verify persistent config.",
        ]
        self.interface = None
        self.ip_address = None
        self.prefix = None
        self.gateway = None
        self.dns = None
        self.connection_name = None

    def generate(self, **params):
        subnet = _random_subnet()
        self.interface = params.get('interface') or _get_practice_interface()
        self.ip_address = params.get('ip', f'192.168.{subnet}.{_random_host()}')
        self.prefix = params.get('prefix', '24')
        self.gateway = params.get('gateway', f'192.168.{subnet}.1')
        self.dns = params.get('dns', random.choice(['8.8.8.8', '1.1.1.1']))
        self.connection_name = params.get('connection') or _get_connection_name(self.interface) or self.interface

        self.description = (
            f"Configure a static IP address on connection '{self.connection_name}':\n"
            f"  - Interface: {self.interface}\n"
            f"  - IP Address: {self.ip_address}/{self.prefix}\n"
            f"  - Gateway: {self.gateway}\n"
            f"  - DNS Server: {self.dns}\n"
            f"  - IPv4 method must be 'manual'\n"
            f"  - Activate the connection\n"
            f"  - Configuration must persist across reboots"
        )

        self.hints = [
            f"nmcli con mod {self.connection_name} ipv4.addresses {self.ip_address}/{self.prefix}",
            f"nmcli con mod {self.connection_name} ipv4.gateway {self.gateway}",
            f"nmcli con mod {self.connection_name} ipv4.dns {self.dns}",
            f"nmcli con mod {self.connection_name} ipv4.method manual",
            f"nmcli con up {self.connection_name}",
            f"Verify: nmcli -f ipv4 con show {self.connection_name}",
        ]
        return self

    def validate(self):
        checks = []
        total = 0

        # 1. IP address active on interface (5 pts)
        actual_ip = get_ip_address(self.interface)
        if actual_ip == self.ip_address:
            checks.append(ValidationCheck("ip_address_set", True, 5,
                          f"IP {self.ip_address} configured on {self.interface}"))
            total += 5
        else:
            checks.append(ValidationCheck("ip_address_set", False, 0,
                          f"IP is {actual_ip}, expected {self.ip_address}", max_points=5))

        # 2. Gateway configured on the connection profile (3 pts)
        #
        # The practice interface (dummy0) is deliberately set up with
        # ipv4.never-default so it can never hijack the box's real default
        # route out from under the candidate's live connection. That means
        # `ip route show default` will never reflect dummy0's gateway even
        # when it's configured correctly, so check the saved profile itself
        # instead of the active routing table.
        conn = get_nmcli_connection_info(self.connection_name)
        configured_gw = conn.get('ipv4.gateway') if conn else None
        if configured_gw == self.gateway:
            checks.append(ValidationCheck("gateway_set", True, 3,
                          f"Gateway {self.gateway} configured on {self.connection_name}"))
            total += 3
        else:
            checks.append(ValidationCheck("gateway_set", False, 0,
                          f"Gateway is {configured_gw}, expected {self.gateway}", max_points=3))

        # 3. DNS configured (2 pts)
        dns_list = get_dns_servers()
        if self.dns in dns_list:
            checks.append(ValidationCheck("dns_set", True, 2,
                          f"DNS {self.dns} configured"))
            total += 2
        else:
            checks.append(ValidationCheck("dns_set", False, 0,
                          f"DNS {self.dns} not in resolv.conf (found {dns_list})", max_points=2))

        # 4. Persistent config via nmcli (3 pts)
        if conn and conn.get('ipv4.method') == 'manual':
            checks.append(ValidationCheck("method_manual", True, 3,
                          "ipv4.method is 'manual' (persistent)"))
            total += 3
        else:
            method = conn.get('ipv4.method', 'unknown') if conn else 'connection not found'
            checks.append(ValidationCheck("method_manual", False, 0,
                          f"ipv4.method is '{method}', expected 'manual'", max_points=3))

        # 5. Interface UP (2 pts)
        state = get_interface_state(self.interface)
        if state == 'UP':
            checks.append(ValidationCheck("interface_up", True, 2,
                          f"Interface {self.interface} is UP"))
            total += 2
        else:
            checks.append(ValidationCheck("interface_up", False, 0,
                          f"Interface {self.interface} is {state}", max_points=2))

        passed = total >= (self.points * 0.7)
        return ValidationResult(self.id, passed, total, self.points, checks)


# ===================================================================
# 2. ConfigureDHCPTask  (medium / 8 pts) [PERSIST]
# ===================================================================

@TaskRegistry.register("networking")
class ConfigureDHCPTask(BaseTask):
    """Configure a connection to obtain an IP address via DHCP."""

    def __init__(self):
        super().__init__(
            id="net_dhcp_001",
            category="networking",
            difficulty="medium",
            points=8
        )
        self.requires_persistence = True
        self.tags = ["nmcli", "dhcp", "ipv4", "persistence"]
        self.exam_tips = [
            "Set ipv4.method to 'auto' for DHCP.",
            "Clear any static addresses with ipv4.addresses ''.",
        ]
        self.connection_name = None
        self.interface = None

    def generate(self, **params):
        self.interface = params.get('interface') or _get_practice_interface()
        self.connection_name = params.get('connection') or _get_connection_name(self.interface) or self.interface

        self.description = (
            f"Configure connection '{self.connection_name}' to use DHCP:\n"
            f"  - Interface: {self.interface}\n"
            f"  - Set IPv4 method to automatic (DHCP)\n"
            f"  - Remove any static IP addresses\n"
            f"  - Activate the connection\n"
            f"  - Configuration must persist across reboots"
        )

        self.hints = [
            f"nmcli con mod {self.connection_name} ipv4.method auto",
            f"nmcli con mod {self.connection_name} ipv4.addresses ''",
            f"nmcli con mod {self.connection_name} ipv4.gateway ''",
            f"nmcli con up {self.connection_name}",
            f"Verify: nmcli -f ipv4.method con show {self.connection_name}",
        ]
        return self

    def validate(self):
        checks = []
        total = 0

        # 1. ipv4.method is auto (4 pts)
        conn = get_nmcli_connection_info(self.connection_name)
        if conn and conn.get('ipv4.method') == 'auto':
            checks.append(ValidationCheck("method_auto", True, 4,
                          "ipv4.method is 'auto' (DHCP)"))
            total += 4
        else:
            method = conn.get('ipv4.method', 'unknown') if conn else 'connection not found'
            checks.append(ValidationCheck("method_auto", False, 0,
                          f"ipv4.method is '{method}', expected 'auto'", max_points=4))

        # 2. Connection is active (2 pts)
        state = get_interface_state(self.interface)
        if state == 'UP':
            checks.append(ValidationCheck("interface_up", True, 2,
                          f"Interface {self.interface} is UP"))
            total += 2
        else:
            checks.append(ValidationCheck("interface_up", False, 0,
                          f"Interface {self.interface} is {state}", max_points=2))

        # 3. No leftover static addresses (2 pts)
        addrs = conn.get('ipv4.addresses', '') if conn else ''
        if not addrs or addrs in ('--', ''):
            checks.append(ValidationCheck("no_static_addr", True, 2,
                          "No leftover static addresses"))
            total += 2
        else:
            checks.append(ValidationCheck("no_static_addr", False, 0,
                          f"Static addresses still configured: {addrs}", max_points=2))

        passed = total >= (self.points * 0.7)
        return ValidationResult(self.id, passed, total, self.points, checks)


# ===================================================================
# 3. SetHostnameTask  (easy / 5 pts) [PERSIST]
# ===================================================================

@TaskRegistry.register("networking")
class SetHostnameTask(BaseTask):
    """Set the system hostname using hostnamectl."""

    has_fault_injection = True

    def __init__(self):
        super().__init__(
            id="net_hostname_001",
            category="networking",
            difficulty="easy",
            points=5
        )
        self.requires_persistence = True
        self.tags = ["hostname", "hostnamectl", "persistence"]
        self.exam_tips = [
            "'hostnamectl set-hostname' writes to /etc/hostname automatically.",
            "Verify with both 'hostname' and 'hostnamectl status'.",
        ]
        self.hostname = None
        self._fault_info = None

    def inject_fault(self):
        """Nothing to break — but record the current hostname so session
        teardown / Reset Machine puts it back instead of leaving the
        exam-generated name on the box."""
        from tasks.troubleshooting import save_fault_state, _run
        r = _run(['hostname'])
        self._fault_info = {'orig_hostname': (r.stdout or '').strip()}
        save_fault_state(self.id, self._fault_info)
        return True, "Recorded current hostname for session cleanup"

    def restore_fault(self):
        from tasks.troubleshooting import clear_fault_state, _run
        orig = (self._fault_info or {}).get('orig_hostname')
        if orig:
            _run(['hostnamectl', 'set-hostname', orig])
        clear_fault_state(self.id)
        return True, (f"Hostname reset to {orig}" if orig
                      else "No previous hostname recorded")

    def generate(self, **params):
        self.hostname = params.get('hostname', _random_hostname())

        self.description = (
            f"Set the system hostname to {self.hostname}, persistently "
            f"across reboots."
        )

        self.hints = [
            f"hostnamectl set-hostname {self.hostname}",
            "Verify: hostnamectl status",
            "Verify: hostname",
            "Check persistent config: cat /etc/hostname",
        ]
        return self

    def validate(self):
        checks = []
        total = 0

        # 1. Current hostname (3 pts)
        result = execute_safe(['hostname'])
        current = result.stdout.strip() if result.success else None
        if current == self.hostname:
            checks.append(ValidationCheck("current_hostname", True, 3,
                          f"Hostname is {self.hostname}"))
            total += 3
        else:
            checks.append(ValidationCheck("current_hostname", False, 0,
                          f"Hostname is '{current}', expected '{self.hostname}'", max_points=3))

        # 2. Persistent in /etc/hostname (2 pts)
        if validate_file_contains('/etc/hostname', self.hostname):
            checks.append(ValidationCheck("persistent_hostname", True, 2,
                          "Hostname persisted in /etc/hostname"))
            total += 2
        else:
            checks.append(ValidationCheck("persistent_hostname", False, 0,
                          "Hostname not found in /etc/hostname", max_points=2))

        passed = total >= (self.points * 0.8)
        return ValidationResult(self.id, passed, total, self.points, checks)


# ===================================================================
# 4. ConfigureDNSTask  (exam / 12 pts) [PERSIST]
# ===================================================================

@TaskRegistry.register("networking")
class ConfigureDNSTask(BaseTask):
    """Configure DNS servers via nmcli."""

    def __init__(self):
        super().__init__(
            id="net_dns_001",
            category="networking",
            difficulty="exam",
            points=12
        )
        self.requires_persistence = True
        self.tags = ["nmcli", "dns", "resolv.conf", "persistence"]
        self.exam_tips = [
            "Never edit /etc/resolv.conf directly on NetworkManager systems.",
            "Use nmcli con mod <name> ipv4.dns to set DNS servers.",
            "Multiple DNS: space-separated in quotes or use +ipv4.dns.",
        ]
        self.dns_servers = None
        self.connection_name = None

    def generate(self, **params):
        self.dns_servers = params.get('dns', _random_dns_pair())
        if isinstance(self.dns_servers, str):
            self.dns_servers = [self.dns_servers]
        iface = _get_practice_interface()
        self.connection_name = params.get('connection') or _get_connection_name(iface) or iface
        dns_str = ' '.join(self.dns_servers)

        self.description = (
            f"Configure DNS servers for connection '{self.connection_name}':\n"
            f"  - Primary DNS: {self.dns_servers[0]}\n"
            f"  - Secondary DNS: {self.dns_servers[1] if len(self.dns_servers) > 1 else 'N/A'}\n"
            f"  - Activate the connection\n"
            f"  - Configuration must persist across reboots"
        )

        self.hints = [
            f"nmcli con mod {self.connection_name} ipv4.dns \"{dns_str}\"",
            f"nmcli con up {self.connection_name}",
            "Verify: cat /etc/resolv.conf",
            f"Verify: nmcli -f ipv4.dns con show {self.connection_name}",
        ]
        return self

    def validate(self):
        checks = []
        total = 0

        # 1. DNS in resolv.conf (5 pts)
        current_dns = get_dns_servers()
        all_found = all(d in current_dns for d in self.dns_servers)
        some_found = any(d in current_dns for d in self.dns_servers)

        if all_found:
            checks.append(ValidationCheck("dns_active", True, 5,
                          f"All DNS servers configured in resolv.conf"))
            total += 5
        elif some_found:
            checks.append(ValidationCheck("dns_active", True, 3,
                          "Some DNS servers configured (partial credit)"))
            total += 3
        else:
            checks.append(ValidationCheck("dns_active", False, 0,
                          f"DNS servers not in resolv.conf. Current: {current_dns}", max_points=5))

        # 2. Persistent in connection profile (4 pts)
        conn = get_nmcli_connection_info(self.connection_name)
        conn_dns = str(conn.get('ipv4.dns', '')) if conn else ''
        persistent_ok = all(d in conn_dns for d in self.dns_servers)
        if persistent_ok:
            checks.append(ValidationCheck("dns_persistent", True, 4,
                          "DNS servers configured persistently in connection profile"))
            total += 4
        elif any(d in conn_dns for d in self.dns_servers):
            checks.append(ValidationCheck("dns_persistent", True, 2,
                          "Some DNS servers persistent (partial credit)"))
            total += 2
        else:
            checks.append(ValidationCheck("dns_persistent", False, 0,
                          "DNS not configured in connection profile", max_points=4))

        # 3. Connection is active (3 pts)
        result = execute_safe(['nmcli', '-t', '-f', 'GENERAL.STATE', 'con', 'show', self.connection_name])
        if result.success and 'activated' in result.stdout.lower():
            checks.append(ValidationCheck("connection_active", True, 3,
                          f"Connection '{self.connection_name}' is active"))
            total += 3
        else:
            checks.append(ValidationCheck("connection_active", False, 0,
                          f"Connection '{self.connection_name}' is not activated", max_points=3))

        passed = total >= (self.points * 0.7)
        return ValidationResult(self.id, passed, total, self.points, checks)


# ===================================================================
# 6. ConfigureHostsFileTask  (easy / 6 pts) [PERSIST]
# ===================================================================

@TaskRegistry.register("networking")
class ConfigureHostsFileTask(BaseTask):
    """Add an entry to /etc/hosts."""

    def __init__(self):
        super().__init__(
            id="net_hosts_file_001",
            category="networking",
            difficulty="easy",
            points=6
        )
        self.requires_persistence = True
        self.tags = ["hosts", "name-resolution", "persistence"]
        self.exam_tips = [
            "/etc/hosts format: <IP>  <FQDN>  <short-name>",
            "Changes to /etc/hosts take effect immediately.",
        ]
        self.ip_address = None
        self.fqdn = None
        self.short_name = None

    def generate(self, **params):
        subnet = _random_subnet()
        host = _random_host()
        self.ip_address = params.get('ip', f'192.168.{subnet}.{host}')
        names = [
            ('appserver.example.com', 'appserver'),
            ('dbserver.example.com', 'dbserver'),
            ('webserver.lab.local', 'webserver'),
            ('fileserver.corp.net', 'fileserver'),
            ('monitor.example.com', 'monitor'),
        ]
        chosen = random.choice(names)
        self.fqdn = params.get('fqdn', chosen[0])
        self.short_name = params.get('short_name', chosen[1])

        self.description = (
            f"Add an entry to /etc/hosts:\n"
            f"  - IP Address: {self.ip_address}\n"
            f"  - FQDN: {self.fqdn}\n"
            f"  - Short name: {self.short_name}\n"
            f"  - The entry must resolve correctly with 'getent hosts'"
        )

        self.hints = [
            f"echo '{self.ip_address}  {self.fqdn}  {self.short_name}' >> /etc/hosts",
            "Verify: getent hosts " + self.fqdn,
            "Verify: cat /etc/hosts",
            "Format: IP  FQDN  alias",
        ]
        return self

    def validate(self):
        checks = []
        total = 0

        # 1. FQDN present in /etc/hosts (3 pts)
        if validate_file_contains('/etc/hosts', self.fqdn):
            checks.append(ValidationCheck("fqdn_in_hosts", True, 3,
                          f"{self.fqdn} found in /etc/hosts"))
            total += 3
        else:
            checks.append(ValidationCheck("fqdn_in_hosts", False, 0,
                          f"{self.fqdn} not found in /etc/hosts", max_points=3))

        # 2. Correct IP maps to FQDN (2 pts)
        result = execute_safe(['getent', 'hosts', self.fqdn])
        if result.success and self.ip_address in result.stdout:
            checks.append(ValidationCheck("ip_resolves", True, 2,
                          f"{self.fqdn} resolves to {self.ip_address}"))
            total += 2
        else:
            checks.append(ValidationCheck("ip_resolves", False, 0,
                          f"{self.fqdn} does not resolve to {self.ip_address}", max_points=2))

        # 3. Short name present (1 pt)
        if validate_file_contains('/etc/hosts', self.short_name):
            checks.append(ValidationCheck("short_name_in_hosts", True, 1,
                          f"Short name '{self.short_name}' present in /etc/hosts"))
            total += 1
        else:
            checks.append(ValidationCheck("short_name_in_hosts", False, 0,
                          f"Short name '{self.short_name}' not in /etc/hosts", max_points=1))

        passed = total >= (self.points * 0.7)
        return ValidationResult(self.id, passed, total, self.points, checks)


# ===================================================================
# 7. CreateNewConnectionTask  (exam / 14 pts) [PERSIST]
# ===================================================================

@TaskRegistry.register("networking")
class CreateNewConnectionTask(BaseTask):
    """Create a brand-new NetworkManager connection with nmcli con add."""

    def __init__(self):
        super().__init__(
            id="net_create_conn_001",
            category="networking",
            difficulty="exam",
            points=14
        )
        self.requires_persistence = True
        self.tags = ["nmcli", "connection", "con-add", "persistence"]
        self.exam_tips = [
            "Use 'nmcli con add' to create, 'nmcli con mod' to modify.",
            "Specify type, con-name, ifname, and IP settings.",
            "'nmcli con add' creates persistent config automatically.",
        ]
        self.connection_name = None
        self.interface = None
        self.ip_address = None
        self.prefix = None
        self.gateway = None

    def generate(self, **params):
        conn_names = ['lab-conn', 'static-prod', 'office-net', 'data-link', 'mgmt-conn']
        subnet = _random_subnet()
        self.connection_name = params.get('connection', random.choice(conn_names))
        try:
            from device.network_manager import get_secondary_interfaces
            secondary = get_secondary_interfaces()
            default_iface = secondary[0] if secondary else _get_practice_interface()
        except Exception:
            default_iface = _get_practice_interface()
        self.interface = params.get('interface') or default_iface
        self.ip_address = params.get('ip', f'10.0.{subnet}.{_random_host()}')
        self.prefix = params.get('prefix', '24')
        self.gateway = params.get('gateway', f'10.0.{subnet}.1')

        self.description = (
            f"Create a NEW network connection from scratch:\n"
            f"  - Connection name: {self.connection_name}\n"
            f"  - Type: ethernet\n"
            f"  - Interface: {self.interface}\n"
            f"  - IP Address: {self.ip_address}/{self.prefix}\n"
            f"  - Gateway: {self.gateway}\n"
            f"  - IPv4 method: manual\n"
            f"  - The connection must be created (not just modified)"
        )

        self.hints = [
            f"nmcli con add type ethernet con-name {self.connection_name} ifname {self.interface} "
            f"ipv4.addresses {self.ip_address}/{self.prefix} ipv4.gateway {self.gateway} ipv4.method manual",
            f"nmcli con up {self.connection_name}",
            f"Verify: nmcli con show {self.connection_name}",
            "Key: 'con add' creates new, 'con mod' modifies existing.",
        ]
        return self

    def validate(self):
        checks = []
        total = 0

        # 1. Connection exists (4 pts)
        conn = get_nmcli_connection_info(self.connection_name)
        if conn:
            checks.append(ValidationCheck("connection_exists", True, 4,
                          f"Connection '{self.connection_name}' exists"))
            total += 4
        else:
            checks.append(ValidationCheck("connection_exists", False, 0,
                          f"Connection '{self.connection_name}' not found", max_points=4))
            return ValidationResult(self.id, False, 0, self.points, checks)

        # 2. Correct interface (2 pts)
        if conn.get('connection.interface-name') == self.interface:
            checks.append(ValidationCheck("correct_interface", True, 2,
                          f"Bound to interface {self.interface}"))
            total += 2
        else:
            checks.append(ValidationCheck("correct_interface", False, 0,
                          f"Interface mismatch: {conn.get('connection.interface-name')}", max_points=2))

        # 3. IP configured (3 pts)
        if self.ip_address in str(conn.get('ipv4.addresses', '')):
            checks.append(ValidationCheck("ip_configured", True, 3,
                          f"IP {self.ip_address}/{self.prefix} configured"))
            total += 3
        else:
            checks.append(ValidationCheck("ip_configured", False, 0,
                          "IP address not configured correctly", max_points=3))

        # 4. Gateway configured (2 pts)
        if self.gateway in str(conn.get('ipv4.gateway', '')):
            checks.append(ValidationCheck("gateway_configured", True, 2,
                          f"Gateway {self.gateway} configured"))
            total += 2
        else:
            checks.append(ValidationCheck("gateway_configured", False, 0,
                          "Gateway not configured", max_points=2))

        # 5. Method is manual (3 pts)
        if conn.get('ipv4.method') == 'manual':
            checks.append(ValidationCheck("method_manual", True, 3,
                          "ipv4.method is 'manual'"))
            total += 3
        else:
            checks.append(ValidationCheck("method_manual", False, 0,
                          f"ipv4.method is '{conn.get('ipv4.method')}'", max_points=3))

        passed = total >= (self.points * 0.7)
        return ValidationResult(self.id, passed, total, self.points, checks)


# ===================================================================
# 8. TroubleshootNetworkTask  (hard / 18 pts)
# ===================================================================

@TaskRegistry.register("networking")
class TroubleshootNetworkTask(BaseTask):
    """Diagnose and fix a network connectivity issue."""

    def __init__(self):
        super().__init__(
            id="net_troubleshoot_001",
            category="networking",
            difficulty="hard",
            points=18
        )
        self.requires_persistence = False
        self.tags = ["troubleshooting", "nmcli", "ip", "diagnostics"]
        self.exam_tips = [
            "Start with 'nmcli device status' and 'nmcli con show'.",
            "Check 'ip addr', 'ip route', 'cat /etc/resolv.conf'.",
            "The connection may need to be created, modified, or activated.",
        ]
        self.connection_name = None
        self.expected_ip = None
        self.expected_gateway = None
        self.expected_dns = None
        self.interface = None

    def generate(self, **params):
        subnet = random.randint(1, 254)
        self.interface = params.get('interface') or _get_practice_interface()
        self.connection_name = params.get('connection') or _get_connection_name(self.interface) or self.interface
        self.expected_ip = params.get('ip', f'192.168.{subnet}.{_random_host()}')
        self.expected_gateway = params.get('gateway', f'192.168.{subnet}.1')
        self.expected_dns = params.get('dns', '8.8.8.8')

        self.description = (
            f"Troubleshoot and fix network connectivity:\n"
            f"  - Connection: {self.connection_name}\n"
            f"  - Interface: {self.interface}\n"
            f"  - Required IP: {self.expected_ip}/24\n"
            f"  - Required Gateway: {self.expected_gateway}\n"
            f"  - Required DNS: {self.expected_dns}\n"
            f"  - Ensure the connection is active and fully functional\n"
            f"  - Configuration must be persistent\n\n"
            f"  Diagnose the issue: the connection may be missing, down,\n"
            f"  misconfigured, or using DHCP instead of static."
        )

        self.hints = [
            "Diagnose: nmcli con show; nmcli device status; ip addr; ip route",
            f"If missing: nmcli con add type ethernet con-name {self.connection_name} ifname {self.interface}",
            f"Set config: nmcli con mod {self.connection_name} ipv4.addresses {self.expected_ip}/24 "
            f"ipv4.gateway {self.expected_gateway} ipv4.dns {self.expected_dns} ipv4.method manual",
            f"Activate: nmcli con up {self.connection_name}",
            "Verify: ip addr; ip route; cat /etc/resolv.conf",
        ]
        return self

    def validate(self):
        checks = []
        total = 0

        # 1. Connection exists (3 pts)
        conn = get_nmcli_connection_info(self.connection_name)
        if conn:
            checks.append(ValidationCheck("connection_exists", True, 3,
                          f"Connection '{self.connection_name}' exists"))
            total += 3
        else:
            checks.append(ValidationCheck("connection_exists", False, 0,
                          f"Connection '{self.connection_name}' not found", max_points=3))

        # 2. IP active (5 pts)
        actual_ip = get_ip_address(self.interface)
        ip_in_config = conn and self.expected_ip in str(conn.get('ipv4.addresses', ''))
        if actual_ip == self.expected_ip:
            checks.append(ValidationCheck("ip_active", True, 5,
                          f"IP {self.expected_ip} is active on {self.interface}"))
            total += 5
        elif ip_in_config:
            checks.append(ValidationCheck("ip_active", True, 3,
                          "IP configured but connection may not be active (partial)"))
            total += 3
        else:
            checks.append(ValidationCheck("ip_active", False, 0,
                          f"IP is {actual_ip}, expected {self.expected_ip}", max_points=5))

        # 3. Gateway active (4 pts)
        gw = get_default_gateway()
        gw_in_config = conn and self.expected_gateway in str(conn.get('ipv4.gateway', ''))
        if gw == self.expected_gateway:
            checks.append(ValidationCheck("gateway_active", True, 4,
                          f"Gateway {self.expected_gateway} is active"))
            total += 4
        elif gw_in_config:
            checks.append(ValidationCheck("gateway_active", True, 2,
                          "Gateway configured but may not be active (partial)"))
            total += 2
        else:
            checks.append(ValidationCheck("gateway_active", False, 0,
                          f"Gateway is {gw}, expected {self.expected_gateway}", max_points=4))

        # 4. DNS configured (3 pts)
        dns_list = get_dns_servers()
        if self.expected_dns in dns_list:
            checks.append(ValidationCheck("dns_configured", True, 3,
                          f"DNS {self.expected_dns} is configured"))
            total += 3
        else:
            checks.append(ValidationCheck("dns_configured", False, 0,
                          f"DNS {self.expected_dns} not found (current: {dns_list})", max_points=3))

        # 5. Interface UP (3 pts)
        state = get_interface_state(self.interface)
        if state == 'UP':
            checks.append(ValidationCheck("interface_up", True, 3,
                          f"Interface {self.interface} is UP"))
            total += 3
        else:
            checks.append(ValidationCheck("interface_up", False, 0,
                          f"Interface {self.interface} is {state}", max_points=3))

        passed = total >= (self.points * 0.7)
        return ValidationResult(self.id, passed, total, self.points, checks)


# ===================================================================
# 10. VerifyNetworkConnectivityTask  (easy / 5 pts)
# ===================================================================

@TaskRegistry.register("networking")
class VerifyNetworkConnectivityTask(BaseTask):
    """Verify network connectivity using ping and basic commands."""

    def __init__(self):
        super().__init__(
            id="net_verify_conn_001",
            category="networking",
            difficulty="easy",
            points=5
        )
        self.requires_persistence = False
        self.tags = ["ping", "connectivity", "diagnostics"]
        self.exam_tips = [
            "Use 'ping -c 1 <host>' for a quick connectivity test.",
            "Check gateway reachability first, then DNS resolution.",
        ]
        self.target_ip = None
        self.interface = None

    def generate(self, **params):
        self.interface = params.get('interface') or _get_practice_interface()
        # Use the current gateway as target for a realistic test
        self.target_ip = params.get('target', '127.0.0.1')

        self.description = (
            f"Verify network connectivity:\n"
            f"  - Confirm interface {self.interface} is UP\n"
            f"  - Confirm an IP address is assigned to {self.interface}\n"
            f"  - Successfully ping {self.target_ip}"
        )

        self.hints = [
            f"ip link show {self.interface}",
            f"ip addr show {self.interface}",
            f"ping -c 2 {self.target_ip}",
            "nmcli device status",
        ]
        return self

    def validate(self):
        checks = []
        total = 0

        # 1. Interface UP (2 pts)
        state = get_interface_state(self.interface)
        if state == 'UP':
            checks.append(ValidationCheck("interface_up", True, 2,
                          f"Interface {self.interface} is UP"))
            total += 2
        else:
            checks.append(ValidationCheck("interface_up", False, 0,
                          f"Interface {self.interface} is {state}", max_points=2))

        # 2. IP assigned (2 pts)
        ip = get_ip_address(self.interface)
        if ip:
            checks.append(ValidationCheck("ip_assigned", True, 2,
                          f"IP {ip} assigned to {self.interface}"))
            total += 2
        else:
            checks.append(ValidationCheck("ip_assigned", False, 0,
                          f"No IP address on {self.interface}", max_points=2))

        # 3. Ping target (1 pt)
        result = execute_safe(['ping', '-c', '1', '-W', '2', self.target_ip])
        if result.success:
            checks.append(ValidationCheck("ping_success", True, 1,
                          f"Ping to {self.target_ip} successful"))
            total += 1
        else:
            checks.append(ValidationCheck("ping_success", False, 0,
                          f"Ping to {self.target_ip} failed", max_points=1))

        passed = total >= (self.points * 0.6)
        return ValidationResult(self.id, passed, total, self.points, checks)


# ===================================================================
# 11. ConfigureIPv6Task  (medium / 10 pts)
# ===================================================================

@TaskRegistry.register("networking")
class ConfigureIPv6Task(BaseTask):
    """Configure an IPv6 address on a connection."""

    def __init__(self):
        super().__init__(
            id="net_ipv6_001",
            category="networking",
            difficulty="medium",
            points=10
        )
        self.requires_persistence = False
        self.tags = ["nmcli", "ipv6", "dual-stack"]
        self.exam_tips = [
            "Use ipv6.addresses and ipv6.method manual for static IPv6.",
            "Verify with 'ip -6 addr show <iface>'.",
            "IPv6 prefix length is typically /64.",
        ]
        self.ipv6_address = None
        self.prefix = None
        self.connection_name = None
        self.interface = None

    def generate(self, **params):
        self.interface = params.get('interface') or _get_practice_interface()
        self.connection_name = params.get('connection') or _get_connection_name(self.interface) or self.interface
        hex_block = format(random.randint(1, 65534), 'x')
        host_block = format(random.randint(1, 65534), 'x')
        self.ipv6_address = params.get('ipv6', f'fd00::{hex_block}:{host_block}')
        self.prefix = params.get('prefix', '64')

        self.description = (
            f"Configure an IPv6 address:\n"
            f"  - Connection: {self.connection_name}\n"
            f"  - Interface: {self.interface}\n"
            f"  - IPv6 Address: {self.ipv6_address}/{self.prefix}\n"
            f"  - IPv6 method: manual\n"
            f"  - Activate the connection"
        )

        self.hints = [
            f"nmcli con mod {self.connection_name} ipv6.addresses {self.ipv6_address}/{self.prefix}",
            f"nmcli con mod {self.connection_name} ipv6.method manual",
            f"nmcli con up {self.connection_name}",
            f"Verify: ip -6 addr show {self.interface}",
            f"Verify: nmcli -f ipv6 con show {self.connection_name}",
        ]
        return self

    def validate(self):
        checks = []
        total = 0

        # 1. IPv6 address present on interface (4 pts)
        result = execute_safe(['ip', '-6', 'addr', 'show', self.interface])
        ipv6_active = result.success and self.ipv6_address in result.stdout
        if ipv6_active:
            checks.append(ValidationCheck("ipv6_active", True, 4,
                          f"IPv6 {self.ipv6_address} active on {self.interface}"))
            total += 4
        else:
            checks.append(ValidationCheck("ipv6_active", False, 0,
                          f"IPv6 {self.ipv6_address} not found on {self.interface}", max_points=4))

        # 2. IPv6 method manual in connection profile (3 pts)
        conn = get_nmcli_connection_info(self.connection_name)
        if conn and conn.get('ipv6.method') == 'manual':
            checks.append(ValidationCheck("ipv6_method", True, 3,
                          "ipv6.method is 'manual'"))
            total += 3
        else:
            method = conn.get('ipv6.method', 'unknown') if conn else 'unknown'
            checks.append(ValidationCheck("ipv6_method", False, 0,
                          f"ipv6.method is '{method}', expected 'manual'", max_points=3))

        # 3. IPv6 address in connection profile (3 pts)
        ipv6_addrs = str(conn.get('ipv6.addresses', '')) if conn else ''
        if self.ipv6_address in ipv6_addrs:
            checks.append(ValidationCheck("ipv6_persistent", True, 3,
                          "IPv6 address in connection profile"))
            total += 3
        else:
            checks.append(ValidationCheck("ipv6_persistent", False, 0,
                          "IPv6 address not in connection profile", max_points=3))

        passed = total >= (self.points * 0.7)
        return ValidationResult(self.id, passed, total, self.points, checks)


# ===================================================================
# 12. RestartNetworkConnectionTask  (easy / 5 pts)
# ===================================================================

@TaskRegistry.register("networking")
class RestartNetworkConnectionTask(BaseTask):
    """Restart (deactivate then activate) a network connection."""

    def __init__(self):
        super().__init__(
            id="net_restart_conn_001",
            category="networking",
            difficulty="easy",
            points=5
        )
        self.requires_persistence = False
        self.tags = ["nmcli", "connection", "restart"]
        self.exam_tips = [
            "Use 'nmcli con down <name>' then 'nmcli con up <name>'.",
            "Alternatively: 'nmcli con up <name>' re-applies config.",
        ]
        self.connection_name = None
        self.interface = None

    def generate(self, **params):
        self.interface = params.get('interface') or _get_practice_interface()
        self.connection_name = params.get('connection') or _get_connection_name(self.interface) or self.interface

        self.description = (
            f"Restart the network connection '{self.connection_name}':\n"
            f"  - Deactivate the connection\n"
            f"  - Re-activate the connection\n"
            f"  - Verify the connection is UP and has an IP address"
        )

        self.hints = [
            f"nmcli con down {self.connection_name}",
            f"nmcli con up {self.connection_name}",
            f"Verify: nmcli con show --active",
            f"Verify: ip addr show {self.interface}",
        ]
        return self

    def validate(self):
        checks = []
        total = 0

        # 1. Connection is active (3 pts)
        result = execute_safe(['nmcli', '-t', '-f', 'GENERAL.STATE', 'con', 'show', self.connection_name])
        if result.success and 'activated' in result.stdout.lower():
            checks.append(ValidationCheck("connection_active", True, 3,
                          f"Connection '{self.connection_name}' is activated"))
            total += 3
        else:
            checks.append(ValidationCheck("connection_active", False, 0,
                          f"Connection '{self.connection_name}' is not active", max_points=3))

        # 2. Interface has IP (2 pts)
        ip = get_ip_address(self.interface)
        if ip:
            checks.append(ValidationCheck("has_ip", True, 2,
                          f"Interface {self.interface} has IP {ip}"))
            total += 2
        else:
            checks.append(ValidationCheck("has_ip", False, 0,
                          f"No IP on {self.interface}", max_points=2))

        passed = total >= (self.points * 0.6)
        return ValidationResult(self.id, passed, total, self.points, checks)


# ===================================================================
# 13. DisplayNetworkInfoTask  (easy / 5 pts)
# ===================================================================

@TaskRegistry.register("networking")
class DisplayNetworkInfoTask(BaseTask):
    """Display and verify current network information."""

    def __init__(self):
        super().__init__(
            id="net_display_info_001",
            category="networking",
            difficulty="easy",
            points=5
        )
        self.requires_persistence = False
        self.tags = ["ip", "nmcli", "ss", "diagnostics"]
        self.exam_tips = [
            "'ip addr' shows addresses, 'ip route' shows routes.",
            "'ss -tulnp' shows listening sockets.",
            "'nmcli device status' gives a quick device overview.",
        ]
        self.interface = None

    def generate(self, **params):
        self.interface = params.get('interface') or _get_primary_interface()

        self.description = (
            f"Verify the following network information for interface {self.interface}:\n"
            f"  - The interface must be in the UP state\n"
            f"  - The interface must have an IPv4 address assigned\n"
            f"  - A default gateway must be present in the routing table\n"
            f"  (Use ip, nmcli, or ss commands to verify)"
        )

        self.hints = [
            f"ip addr show {self.interface}",
            "ip route show default",
            "nmcli device status",
            "ss -tulnp",
        ]
        return self

    def validate(self):
        checks = []
        total = 0

        # 1. Interface UP (2 pts)
        state = get_interface_state(self.interface)
        if state == 'UP':
            checks.append(ValidationCheck("interface_up", True, 2,
                          f"Interface {self.interface} is UP"))
            total += 2
        else:
            checks.append(ValidationCheck("interface_up", False, 0,
                          f"Interface {self.interface} is {state}", max_points=2))

        # 2. Has IP (2 pts)
        ip = get_ip_address(self.interface)
        if ip:
            checks.append(ValidationCheck("has_ip", True, 2,
                          f"IPv4 address: {ip}"))
            total += 2
        else:
            checks.append(ValidationCheck("has_ip", False, 0,
                          f"No IPv4 on {self.interface}", max_points=2))

        # 3. Default gateway exists (1 pt)
        gw = get_default_gateway()
        if gw:
            checks.append(ValidationCheck("has_gateway", True, 1,
                          f"Default gateway: {gw}"))
            total += 1
        else:
            checks.append(ValidationCheck("has_gateway", False, 0,
                          "No default gateway found", max_points=1))

        passed = total >= (self.points * 0.6)
        return ValidationResult(self.id, passed, total, self.points, checks)


# ===================================================================
# 14. ConfigureSearchDomainTask  (medium / 8 pts) [PERSIST]
# ===================================================================

@TaskRegistry.register("networking")
class ConfigureSearchDomainTask(BaseTask):
    """Configure a DNS search domain via nmcli."""

    def __init__(self):
        super().__init__(
            id="net_search_domain_001",
            category="networking",
            difficulty="medium",
            points=8
        )
        self.requires_persistence = True
        self.tags = ["nmcli", "dns", "search-domain", "persistence"]
        self.exam_tips = [
            "Use ipv4.dns-search (not /etc/resolv.conf) to set search domains.",
            "Verify with 'cat /etc/resolv.conf' (look for 'search' line).",
        ]
        self.search_domain = None
        self.connection_name = None

    def generate(self, **params):
        domains = ['example.com', 'lab.local', 'corp.example.com',
                    'test.internal', 'dev.example.net']
        self.search_domain = params.get('domain', random.choice(domains))
        iface = _get_practice_interface()
        self.connection_name = params.get('connection') or _get_connection_name(iface) or iface

        self.description = (
            f"Configure a DNS search domain:\n"
            f"  - Connection: {self.connection_name}\n"
            f"  - Search domain: {self.search_domain}\n"
            f"  - Activate the connection\n"
            f"  - Must persist across reboots"
        )

        self.hints = [
            f"nmcli con mod {self.connection_name} ipv4.dns-search {self.search_domain}",
            f"nmcli con up {self.connection_name}",
            "Verify: cat /etc/resolv.conf  (look for 'search' line)",
            f"Verify: nmcli -f ipv4.dns-search con show {self.connection_name}",
        ]
        return self

    def validate(self):
        checks = []
        total = 0

        # 1. Search domain in resolv.conf (3 pts)
        result = execute_safe(['cat', '/etc/resolv.conf'])
        resolv_ok = False
        if result.success:
            for line in result.stdout.splitlines():
                if line.strip().startswith('search') and self.search_domain in line:
                    resolv_ok = True
                    break
        if resolv_ok:
            checks.append(ValidationCheck("search_active", True, 3,
                          f"Search domain '{self.search_domain}' in resolv.conf"))
            total += 3
        else:
            checks.append(ValidationCheck("search_active", False, 0,
                          f"Search domain '{self.search_domain}' not in resolv.conf", max_points=3))

        # 2. Persistent in connection profile (3 pts)
        conn = get_nmcli_connection_info(self.connection_name)
        dns_search = str(conn.get('ipv4.dns-search', '')) if conn else ''
        if self.search_domain in dns_search:
            checks.append(ValidationCheck("search_persistent", True, 3,
                          "Search domain configured persistently"))
            total += 3
        else:
            checks.append(ValidationCheck("search_persistent", False, 0,
                          "Search domain not in connection profile", max_points=3))

        # 3. Connection active (2 pts)
        result = execute_safe(['nmcli', '-t', '-f', 'GENERAL.STATE', 'con', 'show', self.connection_name])
        if result.success and 'activated' in result.stdout.lower():
            checks.append(ValidationCheck("connection_active", True, 2,
                          f"Connection '{self.connection_name}' is active"))
            total += 2
        else:
            checks.append(ValidationCheck("connection_active", False, 0,
                          f"Connection not active", max_points=2))

        passed = total >= (self.points * 0.7)
        return ValidationResult(self.id, passed, total, self.points, checks)


# ===================================================================
# 15. FullNetworkSetupTask  (exam / 20 pts) [PERSIST]
# ===================================================================

@TaskRegistry.register("networking")
class FullNetworkSetupTask(BaseTask):
    """
    Complete network configuration using a practice dummy interface.
    inject_fault creates dummy0 so the task never touches the live interface.
    """

    has_fault_injection = True
    _DUMMY_IFACE = 'dummy0'
    _CONN_NAME = 'practice-net'

    def __init__(self):
        super().__init__(
            id="net_full_setup_001",
            category="networking",
            difficulty="exam",
            points=20
        )
        self.requires_persistence = True
        self.tags = ["nmcli", "hostnamectl", "full-setup", "persistence", "compound", "fault-injection"]
        self.exam_tips = [
            "Tackle each component: hostname first, then IP/gateway/DNS via nmcli.",
            "'nmcli con add' creates a new connection; 'nmcli con mod' edits an existing one.",
            "Always run 'nmcli con up <name>' after configuring to activate.",
            "Verify: hostnamectl; ip addr show dummy0; nmcli con show practice-net",
        ]
        self.hostname = None
        self.interface = self._DUMMY_IFACE
        self.connection_name = self._CONN_NAME
        self.ip_address = None
        self.prefix = None
        self.gateway = None
        self.dns_servers = None
        self._orig_hostname = None

    def generate(self, **params):
        subnet = _random_subnet()
        self.hostname = params.get('hostname', _random_hostname())
        self.ip_address = params.get('ip', f'192.168.{subnet}.{_random_host()}')
        self.prefix = params.get('prefix', '24')
        self.gateway = params.get('gateway', f'192.168.{subnet}.1')
        self.dns_servers = params.get('dns', _random_dns_pair())
        if isinstance(self.dns_servers, str):
            self.dns_servers = [self.dns_servers]
        dns_str = ', '.join(self.dns_servers)

        self.description = (
            f"Perform a COMPLETE network configuration:\n"
            f"  1. Set system hostname to: {self.hostname}\n"
            f"  2. Create a new nmcli connection named '{self.connection_name}'\n"
            f"     bound to interface: {self.interface}\n"
            f"     - IP Address: {self.ip_address}/{self.prefix}\n"
            f"     - Gateway: {self.gateway}\n"
            f"     - DNS Servers: {dns_str}\n"
            f"     - IPv4 method: manual\n"
            f"  3. Bring the connection up\n"
            f"  ALL settings must persist across reboots.\n"
            f"\n"
            f"  Note: '{self.interface}' is a virtual practice interface — safe to configure."
        )
        self.hints = [
            f"Set hostname: hostnamectl set-hostname {self.hostname}",
            f"Add connection: nmcli con add type dummy ifname {self.interface} con-name {self.connection_name} \\",
            f"  ipv4.method manual ipv4.addresses {self.ip_address}/{self.prefix} \\",
            f"  ipv4.gateway {self.gateway} ipv4.dns \"{' '.join(self.dns_servers)}\"",
            f"Activate: nmcli con up {self.connection_name}",
            f"Verify: ip addr show {self.interface}; nmcli con show {self.connection_name}",
        ]
        return self

    def inject_fault(self):
        import subprocess as _sp
        # Create the dummy kernel module and interface
        _sp.run(['modprobe', 'dummy'], capture_output=True)
        r = _sp.run(['ip', 'link', 'add', self._DUMMY_IFACE, 'type', 'dummy'],
                    capture_output=True, text=True)
        if r.returncode != 0 and 'File exists' not in r.stderr:
            return False, f"Could not create dummy0: {r.stderr.strip()}"
        _sp.run(['ip', 'link', 'set', self._DUMMY_IFACE, 'up'], capture_output=True)

        # Remove any existing practice-net connection so the user starts fresh
        _sp.run(['nmcli', 'con', 'delete', self._CONN_NAME], capture_output=True)

        # Save current hostname for restore
        r2 = _sp.run(['hostname'], capture_output=True, text=True)
        self._orig_hostname = r2.stdout.strip()

        from tasks.troubleshooting import save_fault_state
        save_fault_state(self.id, {
            'orig_hostname': self._orig_hostname,
            'iface': self._DUMMY_IFACE,
            'conn': self._CONN_NAME,
        })
        return True, f"Created {self._DUMMY_IFACE} virtual interface for practice"

    def restore_fault(self):
        import subprocess as _sp
        from tasks.troubleshooting import load_fault_state, clear_fault_state

        state = load_fault_state()
        info = state.get('restore_info', {}) if state else {}
        orig_hostname = info.get('orig_hostname', '')
        iface = info.get('iface', self._DUMMY_IFACE)
        conn = info.get('conn', self._CONN_NAME)

        _sp.run(['nmcli', 'con', 'delete', conn], capture_output=True)
        _sp.run(['ip', 'link', 'delete', iface], capture_output=True)
        if orig_hostname:
            _sp.run(['hostnamectl', 'set-hostname', orig_hostname], capture_output=True)

        clear_fault_state()
        return True, f"Removed {iface}, {conn} connection, restored hostname"

    def validate(self):
        checks = []
        total = 0

        # 1. Hostname (4 pts)
        result = execute_safe(['hostname'])
        current_hostname = result.stdout.strip() if result.success else None
        if current_hostname == self.hostname:
            checks.append(ValidationCheck("hostname_set", True, 4, f"Hostname is {self.hostname}"))
            total += 4
        else:
            checks.append(ValidationCheck("hostname_set", False, 0,
                          f"Hostname is '{current_hostname}', expected '{self.hostname}'", max_points=4))

        # 2. nmcli connection exists with correct profile (6 pts)
        conn = get_nmcli_connection_info(self.connection_name)
        if conn:
            checks.append(ValidationCheck("conn_exists", True, 2, f"Connection '{self.connection_name}' exists"))
            total += 2
            # Check method
            if conn.get('ipv4.method') == 'manual':
                checks.append(ValidationCheck("method_manual", True, 2, "ipv4.method is 'manual'"))
                total += 2
            else:
                checks.append(ValidationCheck("method_manual", False, 0,
                              f"ipv4.method is '{conn.get('ipv4.method', '?')}'", max_points=2))
            # Check address in profile
            addr_field = conn.get('ipv4.addresses', '')
            if self.ip_address in addr_field:
                checks.append(ValidationCheck("ip_in_profile", True, 2,
                              f"IP {self.ip_address} in connection profile"))
                total += 2
            else:
                checks.append(ValidationCheck("ip_in_profile", False, 0,
                              f"IP {self.ip_address} not found in profile (got: {addr_field})", max_points=2))
        else:
            checks.append(ValidationCheck("conn_exists", False, 0,
                          f"Connection '{self.connection_name}' not found", max_points=6))

        # 3. IP address on interface (5 pts)
        actual_ip = get_ip_address(self.interface)
        if actual_ip == self.ip_address:
            checks.append(ValidationCheck("ip_active", True, 5,
                          f"IP {self.ip_address} active on {self.interface}"))
            total += 5
        else:
            checks.append(ValidationCheck("ip_active", False, 0,
                          f"IP on {self.interface} is '{actual_ip}', expected '{self.ip_address}'", max_points=5))

        # 4. DNS servers in profile (3 pts)
        if conn:
            dns_field = conn.get('ipv4.dns', '')
            found = sum(1 for d in self.dns_servers if d in dns_field)
            if found == len(self.dns_servers):
                checks.append(ValidationCheck("dns_configured", True, 3, "DNS servers configured in profile"))
                total += 3
            elif found > 0:
                checks.append(ValidationCheck("dns_configured", True, 1, f"{found}/{len(self.dns_servers)} DNS servers configured"))
                total += 1
            else:
                checks.append(ValidationCheck("dns_configured", False, 0, "DNS not configured in profile", max_points=3))
        else:
            checks.append(ValidationCheck("dns_configured", False, 0, "Connection not found", max_points=3))

        # 5. Interface UP (2 pts)
        state = get_interface_state(self.interface)
        if state == 'UP':
            checks.append(ValidationCheck("interface_up", True, 2, f"{self.interface} is UP"))
            total += 2
        else:
            checks.append(ValidationCheck("interface_up", False, 0, f"{self.interface} is {state}", max_points=2))

        passed = total >= (self.points * 0.7)
        return ValidationResult(self.id, passed, total, self.points, checks)
