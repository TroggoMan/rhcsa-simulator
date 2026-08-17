"""
System-level validators for LVM, networking, filesystems, etc.
"""

import logging
import json
from validators.safe_executor import execute_safe


logger = logging.getLogger(__name__)


# LVM Validators

def validate_pv_exists(device):
    """
    Check if physical volume exists.

    Args:
        device (str): Device path (e.g., '/dev/sdb')

    Returns:
        bool: True if PV exists
    """
    result = execute_safe(['pvs', '--noheadings', device])
    return result.success


def validate_vg_exists(vg_name):
    """
    Check if volume group exists.

    Args:
        vg_name (str): Volume group name

    Returns:
        bool: True if VG exists
    """
    result = execute_safe(['vgs', '--noheadings', vg_name])
    return result.success


def validate_lv_exists(vg_name, lv_name):
    """
    Check if logical volume exists.

    Args:
        vg_name (str): Volume group name
        lv_name (str): Logical volume name

    Returns:
        bool: True if LV exists
    """
    lv_path = f"{vg_name}/{lv_name}"
    result = execute_safe(['lvs', '--noheadings', lv_path])
    return result.success


def get_lv_size_mb(vg_name, lv_name):
    """
    Get logical volume size in MB.

    Args:
        vg_name (str): Volume group name
        lv_name (str): Logical volume name

    Returns:
        int: Size in MB or None
    """
    lv_path = f"{vg_name}/{lv_name}"
    result = execute_safe(['lvs', '--noheadings', '--units', 'm', '--nosuffix', '-o', 'lv_size', lv_path])
    if result.success:
        try:
            # Remove whitespace and convert to int
            size = float(result.stdout.strip())
            return int(size)
        except ValueError:
            pass
    return None


def get_vg_free_space(vg_name):
    """
    Get volume group free space in MB.

    Args:
        vg_name (str): Volume group name

    Returns:
        int: Free space in MB or None
    """
    result = execute_safe(['vgs', '--noheadings', '--units', 'm', '--nosuffix', '-o', 'vg_free', vg_name])
    if result.success:
        try:
            size = float(result.stdout.strip())
            return int(size)
        except ValueError:
            pass
    return None


def get_pv_info(device):
    """
    Get physical volume information.

    Args:
        device (str): Device path

    Returns:
        dict: PV information or None
    """
    result = execute_safe(['pvdisplay', '-C', '--noheadings', device])
    if result.success:
        # Parse output
        return {'exists': True, 'device': device}
    return None


# Filesystem Validators

def get_filesystem_type(device_or_mount):
    """
    Get filesystem type for a device or mount point.

    Args:
        device_or_mount (str): Device path or mount point

    Returns:
        str: Filesystem type (e.g., 'xfs', 'ext4') or None
    """
    # Try with lsblk first
    result = execute_safe(['lsblk', '-no', 'FSTYPE', device_or_mount])
    if result.success and result.stdout:
        return result.stdout.strip()

    # Try with blkid
    result = execute_safe(['blkid', '-s', 'TYPE', '-o', 'value', device_or_mount])
    if result.success and result.stdout:
        return result.stdout.strip()

    return None


def validate_filesystem_type(device, expected_type):
    """
    Validate filesystem type.

    Args:
        device (str): Device path
        expected_type (str): Expected filesystem type

    Returns:
        bool: True if type matches
    """
    actual = get_filesystem_type(device)
    return actual == expected_type


def get_block_device_uuid(device):
    """
    Get UUID for a block device.

    Args:
        device (str): Device path

    Returns:
        str: UUID or None
    """
    result = execute_safe(['blkid', '-s', 'UUID', '-o', 'value', device])
    if result.success:
        return result.stdout.strip()
    return None


def get_mounted_devices():
    """
    Get list of mounted devices.

    Returns:
        list: List of mount point dictionaries
    """
    result = execute_safe(['mount'])
    mounts = []
    if result.success:
        for line in result.stdout.split('\n'):
            if ' on ' in line:
                parts = line.split(' on ')
                if len(parts) >= 2:
                    device = parts[0].strip()
                    rest = parts[1].split(' type ')
                    if len(rest) >= 2:
                        mount_point = rest[0].strip()
                        fstype_and_opts = rest[1].split(' ')
                        fstype = fstype_and_opts[0] if fstype_and_opts else ''
                        mounts.append({
                            'device': device,
                            'mount_point': mount_point,
                            'fstype': fstype
                        })
    return mounts


def validate_persistent_mount(device, mount_point, fstype=None):
    """
    Validate that mount is configured in /etc/fstab.

    Args:
        device (str): Device path or UUID
        mount_point (str): Mount point
        fstype (str): Filesystem type (optional)

    Returns:
        bool: True if entry exists in fstab
    """
    result = execute_safe(['grep', device, '/etc/fstab'])
    if result.success:
        # Check if mount point is also in the line
        if mount_point in result.stdout:
            if fstype:
                return fstype in result.stdout
            return True
    return False


# Swap Validators

def validate_swap_active(device_or_file):
    """
    Check if swap is active.

    Args:
        device_or_file (str): Swap device or file path

    Returns:
        bool: True if swap is active
    """
    result = execute_safe(['swapon', '--show'])
    if result.success:
        return device_or_file in result.stdout
    return False


def get_total_swap():
    """
    Get total swap space in MB.

    Returns:
        int: Total swap in MB or None
    """
    result = execute_safe(['free', '-m'])
    if result.success:
        lines = result.stdout.split('\n')
        for line in lines:
            if line.startswith('Swap:'):
                parts = line.split()
                if len(parts) >= 2:
                    try:
                        return int(parts[1])
                    except ValueError:
                        pass
    return None


# Network Validators

def get_ip_address(interface):
    """
    Get IP address for an interface.

    Args:
        interface (str): Interface name (e.g., 'eth0', 'ens3')

    Returns:
        str: IP address or None
    """
    result = execute_safe(['ip', '-4', 'addr', 'show', interface])
    if result.success:
        for line in result.stdout.split('\n'):
            line = line.strip()
            if line.startswith('inet '):
                parts = line.split()
                if len(parts) >= 2:
                    # Format: "inet 192.168.1.100/24 ..."
                    ip_with_mask = parts[1]
                    ip = ip_with_mask.split('/')[0]
                    return ip
    return None


def get_interface_state(interface):
    """
    Get interface state.

    Args:
        interface (str): Interface name

    Returns:
        str: 'UP' or 'DOWN' or None
    """
    result = execute_safe(['ip', 'link', 'show', interface])
    if result.success:
        if 'state UP' in result.stdout:
            return 'UP'
        elif 'state DOWN' in result.stdout:
            return 'DOWN'
        elif 'state UNKNOWN' in result.stdout:
            # Virtual interfaces (dummy, loopback, ...) have no real carrier
            # to sense, so the kernel reports operstate UNKNOWN even while
            # administratively up. Fall back to the LOWER_UP flag, which is
            # set once such an interface is brought up.
            first_line = result.stdout.split('\n', 1)[0]
            return 'UP' if 'LOWER_UP' in first_line else 'DOWN'
    return None


def validate_interface_ip(interface, expected_ip):
    """
    Validate interface IP address.

    Args:
        interface (str): Interface name
        expected_ip (str): Expected IP address

    Returns:
        bool: True if IP matches
    """
    actual = get_ip_address(interface)
    return actual == expected_ip


def get_default_gateway():
    """
    Get default gateway IP.

    Returns:
        str: Gateway IP or None
    """
    result = execute_safe(['ip', 'route', 'show', 'default'])
    if result.success:
        # Format: "default via 192.168.1.1 dev eth0 ..."
        if 'via' in result.stdout:
            parts = result.stdout.split('via')
            if len(parts) >= 2:
                gateway = parts[1].split()[0]
                return gateway
    return None


def get_dns_servers():
    """
    Get list of DNS servers from /etc/resolv.conf.

    Returns:
        list: List of DNS server IPs
    """
    result = execute_safe(['grep', '^nameserver', '/etc/resolv.conf'])
    dns_servers = []
    if result.success:
        for line in result.stdout.split('\n'):
            if line.startswith('nameserver'):
                parts = line.split()
                if len(parts) >= 2:
                    dns_servers.append(parts[1])
    return dns_servers


def validate_dns_server(expected_dns):
    """
    Validate that DNS server is configured.

    Args:
        expected_dns (str): Expected DNS server IP

    Returns:
        bool: True if DNS server is configured
    """
    dns_servers = get_dns_servers()
    return expected_dns in dns_servers


def get_nmcli_connection_info(connection_name):
    """
    Get nmcli connection information.

    Args:
        connection_name (str): Connection name

    Returns:
        dict: Connection info or None
    """
    result = execute_safe(['nmcli', '-t', '-f', 'ALL', 'connection', 'show', connection_name])
    if result.success:
        info = {}
        for line in result.stdout.split('\n'):
            if ':' in line:
                key, value = line.split(':', 1)
                info[key] = value
        return info
    return None


# Firewall Validators

def is_firewalld_running():
    """
    Check if firewalld is running.

    Returns:
        bool: True if firewalld is active
    """
    result = execute_safe(['systemctl', 'is-active', 'firewalld'])
    return result.success and result.stdout == 'active'


def get_firewall_default_zone():
    """
    Get firewalld default zone.

    Returns:
        str: Default zone name or None
    """
    if not is_firewalld_running():
        return None

    result = execute_safe(['firewall-cmd', '--get-default-zone'])
    if result.success:
        return result.stdout.strip()
    return None


# Cron Validators

def get_user_crontab(username):
    """
    Get user's crontab entries.

    Args:
        username (str): Username

    Returns:
        list: List of crontab entries or None
    """
    result = execute_safe(['crontab', '-l', '-u', username])
    if result.success:
        entries = []
        for line in result.stdout.split('\n'):
            line = line.strip()
            if line and not line.startswith('#'):
                entries.append(line)
        return entries
    return None


def validate_cron_entry(username, search_string):
    """
    Validate that user has a cron entry containing search string.

    Args:
        username (str): Username
        search_string (str): String to search for in cron entries

    Returns:
        bool: True if entry found
    """
    entries = get_user_crontab(username)
    if entries:
        for entry in entries:
            if search_string in entry:
                return True
    return False


# Container Validators (Podman)

def validate_container_running(container_name):
    """
    Check if podman container is running.

    Args:
        container_name (str): Container name or ID

    Returns:
        bool: True if container is running
    """
    result = execute_safe(['podman', 'ps', '-q', '-f', f'name={container_name}'])
    return result.success and len(result.stdout.strip()) > 0


def validate_container_exists(container_name):
    """
    Check if podman container exists (running or stopped).

    Args:
        container_name (str): Container name or ID

    Returns:
        bool: True if container exists
    """
    result = execute_safe(['podman', 'ps', '-a', '-q', '-f', f'name={container_name}'])
    return result.success and len(result.stdout.strip()) > 0


def validate_image_exists(image_name):
    """
    Check if podman image exists.

    Args:
        image_name (str): Image name

    Returns:
        bool: True if image exists
    """
    result = execute_safe(['podman', 'images', '-q', image_name])
    return result.success and len(result.stdout.strip()) > 0


# Archive Validators

def validate_archive_contains(archive_path, file_path):
    """
    Check if tar archive contains a file.

    Args:
        archive_path (str): Path to tar archive
        file_path (str): File path to search for

    Returns:
        bool: True if file is in archive
    """
    result = execute_safe(['tar', '-tf', archive_path])
    if result.success:
        return file_path in result.stdout
    return False


def get_archive_compression(archive_path):
    """
    Detect compression type of archive.

    Args:
        archive_path (str): Path to archive

    Returns:
        str: 'gzip', 'bzip2', 'xz', 'none', or None
    """
    result = execute_safe(['file', archive_path])
    if result.success:
        output = result.stdout.lower()
        if 'gzip' in output:
            return 'gzip'
        elif 'bzip2' in output:
            return 'bzip2'
        elif 'xz' in output:
            return 'xz'
        elif 'tar archive' in output:
            return 'none'
    return None


# Boot Validators

def get_default_target():
    """
    Get the systemd default target.

    Returns:
        str: Default target (e.g., 'multi-user.target') or None
    """
    result = execute_safe(['systemctl', 'get-default'])
    if result.success:
        return result.stdout.strip()
    return None


def validate_default_target(expected_target):
    """
    Validate systemd default target.

    Args:
        expected_target (str): Expected target (e.g., 'graphical.target')

    Returns:
        bool: True if target matches
    """
    actual = get_default_target()
    return actual == expected_target


def get_grub_default_entry():
    """
    Get GRUB default boot entry from /etc/default/grub.

    Returns:
        str: Default entry or None
    """
    result = execute_safe(['grep', '^GRUB_DEFAULT=', '/etc/default/grub'])
    if result.success:
        # Format: GRUB_DEFAULT=0 or GRUB_DEFAULT=saved
        line = result.stdout.strip()
        if '=' in line:
            return line.split('=', 1)[1].strip('"\'')
    return None


def get_grub_timeout():
    """
    Get GRUB timeout value from /etc/default/grub.

    Returns:
        int: Timeout in seconds or None
    """
    result = execute_safe(['grep', '^GRUB_TIMEOUT=', '/etc/default/grub'])
    if result.success:
        line = result.stdout.strip()
        if '=' in line:
            value = line.split('=', 1)[1].strip('"\'')
            try:
                return int(value)
            except ValueError:
                pass
    return None


def validate_grub_timeout(expected_timeout):
    """
    Validate GRUB timeout setting.

    Args:
        expected_timeout (int): Expected timeout in seconds

    Returns:
        bool: True if timeout matches
    """
    actual = get_grub_timeout()
    return actual == expected_timeout


def get_grub_cmdline():
    """
    Get GRUB kernel command line from /etc/default/grub.

    Returns:
        str: Command line parameters or None
    """
    result = execute_safe(['grep', '^GRUB_CMDLINE_LINUX=', '/etc/default/grub'])
    if result.success:
        line = result.stdout.strip()
        if '=' in line:
            return line.split('=', 1)[1].strip('"\'')
    return None


def validate_grub_parameter(parameter):
    """
    Check if a parameter exists in GRUB kernel command line.

    Args:
        parameter (str): Parameter to check (e.g., 'quiet', 'rhgb')

    Returns:
        bool: True if parameter is present
    """
    cmdline = get_grub_cmdline()
    if cmdline:
        return parameter in cmdline.split()
    return False


def validate_grub_parameter_value(parameter, expected_value):
    """
    Check if a parameter has the expected value in GRUB command line.

    Args:
        parameter (str): Parameter name (e.g., 'console')
        expected_value (str): Expected value

    Returns:
        bool: True if parameter=value exists
    """
    cmdline = get_grub_cmdline()
    if cmdline:
        search_str = f"{parameter}={expected_value}"
        return search_str in cmdline
    return False


def is_grub_config_updated():
    """
    Check if /boot/grub2/grub.cfg exists and has been recently modified.
    Note: This is a basic check, real validation would require comparing timestamps.

    Returns:
        bool: True if grub.cfg exists
    """
    import os
    grub_cfg_paths = [
        '/boot/grub2/grub.cfg',
        '/boot/efi/EFI/redhat/grub.cfg',
        '/boot/efi/EFI/centos/grub.cfg'
    ]

    for path in grub_cfg_paths:
        if os.path.exists(path):
            return True
    return False
