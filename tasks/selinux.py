"""
SELinux management tasks for RHCSA EX200 v10 exam.
Covers modes, contexts, booleans, ports, troubleshooting, AVC analysis,
user mappings, service diagnostics, and filesystem relabeling.
"""

import os
import random
import logging
from tasks.base import BaseTask
from tasks.registry import TaskRegistry
from core.validator import ValidationCheck, ValidationResult
from validators.safe_executor import execute_safe


logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# 1. SetSELinuxModeTask (easy / 5 pts) [PERSIST]
# ---------------------------------------------------------------------------
@TaskRegistry.register("selinux")
class SetSELinuxModeTask(BaseTask):
    """Set SELinux enforcing mode at runtime and persistently."""

    def __init__(self):
        super().__init__(
            id="selinux_mode_001",
            category="selinux",
            difficulty="easy",
            points=5,
        )
        self.requires_persistence = True
        self.tags = ["selinux", "mode", "config"]
        self.exam_tips = [
            "Use 'setenforce 1' or 'setenforce 0' for immediate change.",
            "Edit /etc/selinux/config and set SELINUX=enforcing|permissive for persistence.",
            "You CANNOT switch from disabled to enforcing at runtime -- a reboot is required.",
        ]
        self.mode = None

    def generate(self, **params):
        self.mode = params.get("mode", random.choice(["Enforcing", "Permissive"]))

        self.description = (
            f"Set SELinux to {self.mode} mode:\n"
            f"  1. Change the current runtime mode to {self.mode}\n"
            f"  2. Ensure the mode persists after reboot by editing /etc/selinux/config\n"
            f"\n"
            f"Verification commands:\n"
            f"  - getenforce\n"
            f"  - grep ^SELINUX= /etc/selinux/config"
        )

        self.hints = [
            f"Use 'setenforce {0 if self.mode == 'Permissive' else 1}' for the runtime change",
            "Edit /etc/selinux/config and set SELINUX= to the lowercase mode name",
            "Verify current mode with 'getenforce'",
            "Verify persistent config with 'grep ^SELINUX= /etc/selinux/config'",
        ]

        return self

    def validate(self):
        checks = []
        total_points = 0

        # Check 1: Current runtime mode (2 pts)
        result = execute_safe(["getenforce"])
        if result.success and result.stdout.strip().lower() == self.mode.lower():
            checks.append(ValidationCheck(
                name="runtime_mode",
                passed=True,
                points=2,
                message=f"SELinux runtime mode is {self.mode}",
            ))
            total_points += 2
        else:
            actual = result.stdout.strip() if result.success else "unknown"
            checks.append(ValidationCheck(
                name="runtime_mode",
                passed=False,
                points=0,
                max_points=2,
                message=f"SELinux runtime mode: expected {self.mode}, got {actual}",
            ))

        # Check 2: Persistent config (3 pts)
        result = execute_safe(["grep", "^SELINUX=", "/etc/selinux/config"])
        expected = f"selinux={self.mode.lower()}"
        if result.success and expected in result.stdout.lower().replace(" ", ""):
            checks.append(ValidationCheck(
                name="persistent_mode",
                passed=True,
                points=3,
                message="SELinux mode configured persistently in /etc/selinux/config",
            ))
            total_points += 3
        else:
            checks.append(ValidationCheck(
                name="persistent_mode",
                passed=False,
                points=0,
                max_points=3,
                message="/etc/selinux/config does not have the correct SELINUX= line",
            ))

        passed = total_points >= (self.points * 0.6)
        return ValidationResult(self.id, passed, total_points, self.points, checks)


# ---------------------------------------------------------------------------
# 2. SetSELinuxContextTask (exam / 12 pts) [PERSIST]
# ---------------------------------------------------------------------------
@TaskRegistry.register("selinux")
class SetSELinuxContextTask(BaseTask):
    """Set SELinux file context with semanage fcontext + restorecon."""

    def __init__(self):
        super().__init__(
            id="selinux_context_001",
            category="selinux",
            difficulty="exam",
            points=12,
        )
        self.requires_persistence = True
        self.tags = ["selinux", "fcontext", "restorecon"]
        self.exam_tips = [
            "Always use semanage fcontext FIRST, then restorecon -Rv.",
            "The path regex must end with (/.*)?  to cover all children.",
            "chcon changes are NOT persistent -- they are lost on relabel.",
        ]
        self.directory = None
        self.context_type = None

    def generate(self, **params):
        dir_suffix = random.randint(1, 99)
        self.directory = params.get("directory", f"/srv/web{dir_suffix}")

        context_options = [
            ("httpd_sys_content_t", "web server content"),
            ("public_content_t", "public read-only content via NFS/FTP"),
            ("samba_share_t", "Samba file sharing"),
            ("nfs_t", "NFS exported content"),
            ("httpd_sys_rw_content_t", "writable web application data"),
        ]
        self.context_type, context_desc = random.choice(context_options)

        self.description = (
            f"Configure SELinux file context for '{self.directory}':\n"
            f"  1. Create the directory if it does not exist\n"
            f"  2. Set the SELinux type to: {self.context_type}\n"
            f"  3. Apply the context recursively to all current files\n"
            f"  4. Make the change persistent across filesystem relabels\n"
            f"\n"
            f"Purpose: This directory will serve {context_desc}."
        )

        self.hints = [
            f"Create the directory first if it doesn't exist",
            "semanage fcontext sets a persistent policy rule; restorecon applies it to disk",
            f"Pattern for directories: 'semanage fcontext -a -t TYPE PATH(/.*)?'",
            f"Verify the context landed: ls -Zd {self.directory}",
        ]

        return self

    def validate(self):
        checks = []
        total_points = 0

        # Check 1: Directory exists (2 pts)
        result = execute_safe(["test", "-d", self.directory])
        if result.success:
            checks.append(ValidationCheck(
                name="directory_exists",
                passed=True,
                points=2,
                message=f"Directory '{self.directory}' exists",
            ))
            total_points += 2
        else:
            checks.append(ValidationCheck(
                name="directory_exists",
                passed=False,
                points=0,
                max_points=2,
                message=f"Directory '{self.directory}' not found",
            ))
            return ValidationResult(self.id, False, total_points, self.points, checks)

        # Check 2: Current context on directory (5 pts)
        result = execute_safe(["ls", "-Zd", self.directory])
        if result.success and self.context_type in result.stdout:
            checks.append(ValidationCheck(
                name="current_context",
                passed=True,
                points=5,
                message=f"Directory has correct SELinux type: {self.context_type}",
            ))
            total_points += 5
        else:
            actual = result.stdout.strip() if result.success else "unknown"
            checks.append(ValidationCheck(
                name="current_context",
                passed=False,
                points=0,
                max_points=5,
                message=f"SELinux type mismatch on directory (got: {actual})",
            ))

        # Check 3: Persistent fcontext rule via semanage (5 pts)
        result = execute_safe(["semanage", "fcontext", "-l"])
        if result.success and self.directory in result.stdout and self.context_type in result.stdout:
            checks.append(ValidationCheck(
                name="persistent_fcontext",
                passed=True,
                points=5,
                message="Persistent fcontext rule configured via semanage",
            ))
            total_points += 5
        else:
            checks.append(ValidationCheck(
                name="persistent_fcontext",
                passed=False,
                points=0,
                max_points=5,
                message="No persistent fcontext rule found (use 'semanage fcontext -a ...')",
            ))

        passed = total_points >= (self.points * 0.7)
        return ValidationResult(self.id, passed, total_points, self.points, checks)


# ---------------------------------------------------------------------------
# 3. SetSELinuxBooleanTask (exam / 8 pts) [PERSIST]
# ---------------------------------------------------------------------------
@TaskRegistry.register("selinux")
class SetSELinuxBooleanTask(BaseTask):
    """Enable or disable an SELinux boolean persistently."""

    def __init__(self):
        super().__init__(
            id="selinux_boolean_001",
            category="selinux",
            difficulty="exam",
            points=8,
        )
        self.requires_persistence = True
        self.tags = ["selinux", "boolean", "setsebool"]
        self.exam_tips = [
            "setsebool -P makes the change survive reboots.",
            "Without -P the boolean reverts on next boot.",
            "getsebool -a lists all booleans and their current state.",
        ]
        self.boolean_name = None
        self.boolean_value = None

    def generate(self, **params):
        boolean_options = [
            ("httpd_can_network_connect", "on", "allow Apache to make outgoing network connections"),
            ("httpd_enable_homedirs", "on", "allow Apache to serve user home directories"),
            ("ftpd_anon_write", "on", "allow anonymous FTP write access"),
            ("samba_enable_home_dirs", "on", "allow Samba to share user home directories"),
            ("httpd_can_network_connect_db", "on", "allow Apache to connect to database servers"),
            ("virt_use_nfs", "on", "allow virtual machines to use NFS mounts"),
            ("httpd_use_nfs", "on", "allow Apache to serve content from NFS"),
        ]

        self.boolean_name, self.boolean_value, purpose = random.choice(boolean_options)

        self.description = (
            f"Configure SELinux boolean:\n"
            f"  - Boolean: {self.boolean_name}\n"
            f"  - Set value to: {self.boolean_value}\n"
            f"  - Make the change persistent across reboots\n"
            f"\n"
            f"Purpose: {purpose}"
        )

        self.hints = [
            f"setsebool -P {self.boolean_name} {self.boolean_value}",
            f"Verify: getsebool {self.boolean_name}",
            "The -P flag writes to the policy store for persistence",
            "List all booleans: getsebool -a | grep httpd",
        ]

        return self

    def validate(self):
        checks = []
        total_points = 0

        # Check 1: Runtime boolean value (4 pts)
        result = execute_safe(["getsebool", self.boolean_name])
        expected_state = self.boolean_value  # "on" or "off"
        if result.success and f"--> {expected_state}" in result.stdout:
            checks.append(ValidationCheck(
                name="boolean_runtime",
                passed=True,
                points=4,
                message=f"Boolean '{self.boolean_name}' is {expected_state}",
            ))
            total_points += 4
        else:
            actual = result.stdout.strip() if result.success else "unknown"
            checks.append(ValidationCheck(
                name="boolean_runtime",
                passed=False,
                points=0,
                max_points=4,
                message=f"Boolean value incorrect: expected {expected_state}, got: {actual}",
            ))

        # Check 2: Persistent configuration via semanage boolean -l (4 pts)
        result = execute_safe(["semanage", "boolean", "-l"])
        if result.success:
            found_persistent = False
            for line in result.stdout.splitlines():
                if self.boolean_name in line:
                    # semanage boolean -l shows: (on , on) or (off , on), etc.
                    # The first value is the current, the second is the default.
                    if f"({expected_state}" in line.replace(" ", "").lower():
                        found_persistent = True
                    break

            if found_persistent:
                checks.append(ValidationCheck(
                    name="boolean_persistent",
                    passed=True,
                    points=4,
                    message="Boolean is configured persistently (setsebool -P)",
                ))
                total_points += 4
            else:
                checks.append(ValidationCheck(
                    name="boolean_persistent",
                    passed=False,
                    points=0,
                    max_points=4,
                    message="Boolean is NOT persistently set (did you use -P flag?)",
                ))
        else:
            checks.append(ValidationCheck(
                name="boolean_persistent",
                passed=False,
                points=0,
                max_points=4,
                message="Could not query persistent boolean state",
            ))

        passed = total_points >= (self.points * 0.7)
        return ValidationResult(self.id, passed, total_points, self.points, checks)


# ---------------------------------------------------------------------------
# 4. SetSELinuxPortTask (exam / 12 pts) [PERSIST]
# ---------------------------------------------------------------------------
@TaskRegistry.register("selinux")
class SetSELinuxPortTask(BaseTask):
    """Add an SELinux port context with semanage port."""

    def __init__(self):
        super().__init__(
            id="selinux_port_001",
            category="selinux",
            difficulty="exam",
            points=12,
        )
        self.requires_persistence = True
        self.tags = ["selinux", "port", "semanage"]
        self.exam_tips = [
            "semanage port -a -t <type> -p tcp <port>",
            "If the port is already defined, use -m (modify) instead of -a.",
            "semanage port -l | grep <port> to verify.",
        ]
        self.port = None
        self.protocol = None
        self.context_type = None

    def generate(self, **params):
        port_options = [
            (8080, "tcp", "http_port_t", "HTTP"),
            (8443, "tcp", "http_port_t", "HTTPS"),
            (2222, "tcp", "ssh_port_t", "SSH"),
            (9090, "tcp", "http_port_t", "Cockpit/HTTP"),
            (3131, "tcp", "http_port_t", "HTTP application"),
            (8888, "tcp", "http_port_t", "HTTP proxy"),
            (2049, "udp", "nfs_port_t", "NFS"),
        ]

        choice = random.choice(port_options)
        self.port = params.get("port", choice[0])
        self.protocol = params.get("protocol", choice[1])
        self.context_type = params.get("context", choice[2])
        port_desc = choice[3]

        self.description = (
            f"Configure SELinux to allow a service on a non-standard port:\n"
            f"  - Port: {self.port}/{self.protocol}\n"
            f"  - SELinux type: {self.context_type}\n"
            f"  - Purpose: Allow {port_desc} service on port {self.port}\n"
            f"  - Make the change persistent"
        )

        self.hints = [
            f"semanage port -a -t {self.context_type} -p {self.protocol} {self.port}",
            f"If port is already assigned, use: semanage port -m -t {self.context_type} -p {self.protocol} {self.port}",
            f"Verify: semanage port -l | grep {self.port}",
            "Common port types: http_port_t, ssh_port_t, ftp_port_t, smtp_port_t",
        ]

        return self

    def validate(self):
        checks = []
        total_points = 0

        # Check 1: Port context exists in semanage port -l (12 pts)
        result = execute_safe(["semanage", "port", "-l"])
        if result.success:
            found = False
            for line in result.stdout.splitlines():
                if self.context_type in line and str(self.port) in line:
                    # Verify protocol
                    if self.protocol in line:
                        found = True
                        break

            if found:
                checks.append(ValidationCheck(
                    name="port_context",
                    passed=True,
                    points=12,
                    message=f"Port {self.port}/{self.protocol} has SELinux type {self.context_type}",
                ))
                total_points += 12
            else:
                checks.append(ValidationCheck(
                    name="port_context",
                    passed=False,
                    points=0,
                    max_points=12,
                    message=f"Port {self.port}/{self.protocol} not assigned to {self.context_type}",
                ))
        else:
            checks.append(ValidationCheck(
                name="port_context",
                passed=False,
                points=0,
                max_points=12,
                message="Could not query SELinux port contexts (is policycoreutils-python-utils installed?)",
            ))

        passed = total_points >= (self.points * 0.7)
        return ValidationResult(self.id, passed, total_points, self.points, checks)


# ---------------------------------------------------------------------------
# 5. TroubleshootSELinuxDenialTask (exam / 18 pts) [PERSIST] [EXAM-SEEN]
# ---------------------------------------------------------------------------
@TaskRegistry.register("selinux")
class TroubleshootSELinuxDenialTask(BaseTask):
    """Troubleshoot and fix an SELinux denial using audit2why / sealert."""

    has_fault_injection = True

    def __init__(self):
        super().__init__(
            id="selinux_denial_001",
            category="selinux",
            difficulty="exam",
            points=18,
        )
        self.requires_persistence = True
        self.tags = ["selinux", "troubleshoot", "audit2why", "sealert", "exam-seen"]
        self.exam_tips = [
            "Start with: ausearch -m avc -ts recent | audit2why",
            "sealert -a /var/log/audit/audit.log gives human-readable suggestions.",
            "Most fixes involve one of: setsebool -P, semanage fcontext + restorecon, or semanage port.",
            "Read the audit2why output carefully -- it tells you EXACTLY what to do.",
        ]
        self.service = None
        self.directory = None
        self.expected_context = None
        self.fix_type = None

    def generate(self, **params):
        scenarios = [
            ("httpd", "/var/www/custom", "httpd_sys_content_t", "fcontext",
             "Apache cannot serve files from a custom directory"),
            ("httpd", "/srv/webapp", "httpd_sys_rw_content_t", "fcontext",
             "Apache cannot write to an application data directory"),
            ("samba", "/srv/shares", "samba_share_t", "fcontext",
             "Samba cannot access files in the share directory"),
            ("nginx", "/opt/webdata", "httpd_sys_content_t", "fcontext",
             "Nginx cannot serve files from /opt/webdata"),
            ("httpd", None, "httpd_can_network_connect", "boolean",
             "Apache cannot make outgoing network connections to a backend"),
        ]

        scenario = random.choice(scenarios)
        self.service = scenario[0]
        self.directory = params.get("directory", scenario[1])
        self.expected_context = scenario[2]
        self.fix_type = scenario[3]
        symptom = scenario[4]

        if self.fix_type == "fcontext":
            self.description = (
                f"An SELinux denial is preventing '{self.service}' from functioning correctly.\n"
                f"\n"
                f"Symptom: {symptom}\n"
                f"Directory: {self.directory}\n"
                f"\n"
                f"Tasks:\n"
                f"  1. Identify the denial using audit logs / audit2why / sealert\n"
                f"  2. Fix the SELinux file context on '{self.directory}' and all contents\n"
                f"  3. Make the fix persistent across relabels\n"
                f"  4. Verify the service can access the directory"
            )
            self.hints = [
                "Check the audit log: ausearch -m avc -ts recent | audit2why",
                f"The directory needs the correct SELinux type for {self.service} to access it",
                "Use semanage fcontext to make the change persistent, then apply it",
            ]
        else:  # boolean
            self.description = (
                f"An SELinux denial is preventing '{self.service}' from functioning correctly.\n"
                f"\n"
                f"Symptom: {symptom}\n"
                f"\n"
                f"Tasks:\n"
                f"  1. Identify the denial using audit logs / audit2why / sealert\n"
                f"  2. Fix the issue by enabling the appropriate SELinux boolean\n"
                f"  3. Make the fix persistent across reboots"
            )
            self.hints = [
                "ausearch -m avc -ts recent | audit2why",
                "sealert -a /var/log/audit/audit.log",
                f"setsebool -P {self.expected_context} on",
                "getsebool -a | grep httpd",
            ]

        return self

    def _fcontext_avc(self, test_file):
        """Build (avc_body, journal_msg) for the fcontext scenario's synthetic
        denial. None of these directories are wired into the service's real
        config (no vhost/share/alias points at them), so the service never
        actually touches them and a genuine denial can't be relied on to
        occur -- seed the evidence a real one would have left instead."""
        perm = 'write' if self.expected_context == 'httpd_sys_rw_content_t' else 'read'
        comm, scontext_type = {
            'httpd': ('httpd', 'httpd_t'),
            'nginx': ('nginx', 'httpd_t'),
            'samba': ('smbd', 'smbd_t'),
        }.get(self.service, (self.service, 'httpd_t'))
        avc_body = (
            f'{{ {perm} }} for  pid=2841 comm="{comm}" name="index.html" '
            'dev="dm-0" ino=17825828 '
            f'scontext=system_u:system_r:{scontext_type}:s0 '
            'tcontext=unconfined_u:object_r:tmp_t:s0 tclass=file permissive=0'
        )
        journal_msg = (
            f'SELinux is preventing {comm} from {perm} access on the file '
            f'{test_file}. For complete SELinux messages run: ausearch -m AVC | audit2why'
        )
        return avc_body, journal_msg

    def inject_fault(self):
        import subprocess as _sp
        if self.fix_type == 'fcontext' and self.directory:
            os.makedirs(self.directory, exist_ok=True)
            test_file = os.path.join(self.directory, 'index.html')
            if not os.path.exists(test_file):
                with open(test_file, 'w') as f:
                    f.write('<html><body>Test</body></html>\n')
            _sp.run(['chcon', '-Rt', 'tmp_t', self.directory], capture_output=True)
            from tasks.troubleshooting import save_fault_state, _seed_avc_denial
            save_fault_state(self.id, {'directory': self.directory, 'fix_type': self.fix_type})
            _seed_avc_denial(*self._fcontext_avc(test_file))
            return True, f"Created {self.directory} with wrong SELinux context (tmp_t)"

        # boolean fix_type: actually turn the boolean off so there is a real
        # fault to find and fix, and seed matching AVC evidence so
        # `ausearch -m avc -ts recent | audit2why` has something to show
        # (nothing else here ever makes httpd originate an outbound
        # connection, so a genuine denial can't be relied on to occur).
        from tasks.troubleshooting import save_fault_state, _seed_avc_denial

        original_value = 'on'
        r = _sp.run(['getsebool', self.expected_context], capture_output=True, text=True)
        if r.returncode == 0 and '-->' in r.stdout:
            original_value = r.stdout.split('-->')[-1].strip().split()[0]

        _sp.run(['setsebool', '-P', self.expected_context, 'off'], capture_output=True)
        save_fault_state(self.id, {
            'fix_type': self.fix_type,
            'boolean': self.expected_context,
            'original_value': original_value,
        })

        _seed_avc_denial(
            '{ name_connect } for  pid=2841 comm="httpd" dest=8080 '
            'scontext=system_u:system_r:httpd_t:s0 '
            'tcontext=system_u:object_r:http_cache_port_t:s0 '
            'tclass=tcp_socket permissive=0',
            'SELinux is preventing /usr/sbin/httpd from name_connect access '
            'on the tcp_socket port 8080. For complete SELinux messages '
            'run: ausearch -m AVC | audit2why')

        return True, f"Set {self.expected_context}=off (was {original_value})"

    def restore_fault(self):
        import subprocess as _sp
        import shutil
        from tasks.troubleshooting import load_fault_state, clear_fault_state
        state = load_fault_state(self.id)
        info = state.get('restore_info', {}) if state else {}

        if info.get('fix_type') == 'boolean':
            name = info.get('boolean')
            original = info.get('original_value', 'on')
            if name:
                _sp.run(['setsebool', '-P', name, original], capture_output=True)
            clear_fault_state(self.id)
            return True, f"Restored {name}={original}"

        directory = info.get('directory', self.directory)
        if directory and os.path.exists(directory):
            _sp.run(['restorecon', '-Rv', directory], capture_output=True)
            shutil.rmtree(directory, ignore_errors=True)
        clear_fault_state(self.id)
        return True, f"Removed {directory}"

    def validate(self):
        checks = []
        total_points = 0

        if self.fix_type == "fcontext":
            # Check 1: Directory exists (3 pts)
            result = execute_safe(["test", "-d", self.directory])
            if result.success:
                checks.append(ValidationCheck(
                    name="directory_exists",
                    passed=True,
                    points=3,
                    message=f"Directory '{self.directory}' exists",
                ))
                total_points += 3
            else:
                checks.append(ValidationCheck(
                    name="directory_exists",
                    passed=False,
                    points=0,
                    max_points=3,
                    message=f"Directory '{self.directory}' not found",
                ))
                return ValidationResult(self.id, False, total_points, self.points, checks)

            # Check 2: Current context on directory (7 pts)
            result = execute_safe(["ls", "-Zd", self.directory])
            if result.success and self.expected_context in result.stdout:
                checks.append(ValidationCheck(
                    name="current_context",
                    passed=True,
                    points=7,
                    message=f"Directory context is {self.expected_context}",
                ))
                total_points += 7
            else:
                actual = result.stdout.strip() if result.success else "unknown"
                checks.append(ValidationCheck(
                    name="current_context",
                    passed=False,
                    points=0,
                    max_points=7,
                    message=f"Context incorrect: expected {self.expected_context}, got: {actual}",
                ))

            # Check 3: Persistent fcontext rule (8 pts)
            result = execute_safe(["semanage", "fcontext", "-l"])
            if result.success and self.directory in result.stdout and self.expected_context in result.stdout:
                checks.append(ValidationCheck(
                    name="persistent_fcontext",
                    passed=True,
                    points=8,
                    message="Persistent fcontext rule configured",
                ))
                total_points += 8
            else:
                checks.append(ValidationCheck(
                    name="persistent_fcontext",
                    passed=False,
                    points=0,
                    max_points=8,
                    message="No persistent fcontext rule found for directory",
                ))

        else:  # boolean fix
            # Check 1: Boolean is on (9 pts)
            result = execute_safe(["getsebool", self.expected_context])
            if result.success and "--> on" in result.stdout:
                checks.append(ValidationCheck(
                    name="boolean_enabled",
                    passed=True,
                    points=9,
                    message=f"Boolean '{self.expected_context}' is enabled",
                ))
                total_points += 9
            else:
                checks.append(ValidationCheck(
                    name="boolean_enabled",
                    passed=False,
                    points=0,
                    max_points=9,
                    message=f"Boolean '{self.expected_context}' is not enabled",
                ))

            # Check 2: Boolean is persistent (9 pts)
            result = execute_safe(["semanage", "boolean", "-l"])
            if result.success:
                persistent = False
                for line in result.stdout.splitlines():
                    if self.expected_context in line and "(on" in line.replace(" ", ""):
                        persistent = True
                        break
                if persistent:
                    checks.append(ValidationCheck(
                        name="boolean_persistent",
                        passed=True,
                        points=9,
                        message="Boolean is persistently enabled",
                    ))
                    total_points += 9
                else:
                    checks.append(ValidationCheck(
                        name="boolean_persistent",
                        passed=False,
                        points=0,
                        max_points=9,
                        message="Boolean is NOT persistently set (use setsebool -P)",
                    ))
            else:
                checks.append(ValidationCheck(
                    name="boolean_persistent",
                    passed=False,
                    points=0,
                    max_points=9,
                    message="Could not verify persistent boolean configuration",
                ))

        passed = total_points >= (self.points * 0.7)
        return ValidationResult(self.id, passed, total_points, self.points, checks)


# ---------------------------------------------------------------------------
# 6. SELinuxAVCAnalysisTask (hard / 18 pts) [EXAM-SEEN]
# ---------------------------------------------------------------------------
@TaskRegistry.register("selinux")
class SELinuxAVCAnalysisTask(BaseTask):
    """Read and interpret AVC denial messages from audit.log."""

    def __init__(self):
        super().__init__(
            id="selinux_avc_analysis_001",
            category="selinux",
            difficulty="hard",
            points=18,
        )
        self.requires_persistence = False
        self.tags = ["selinux", "avc", "audit", "analysis", "exam-seen"]
        self.exam_tips = [
            "Use 'ausearch -m avc -ts recent' to find recent denials.",
            "Pipe to audit2why for human-readable recommendations.",
            "sealert -a /var/log/audit/audit.log gives detailed fix suggestions.",
            "The AVC message tells you: source context, target context, class, and permission.",
        ]
        self.target_dir = None
        self.correct_type = None
        self.service_domain = None

    def generate(self, **params):
        scenarios = [
            ("/var/www/reports", "httpd_sys_content_t", "httpd_t",
             "Apache", "read", "file"),
            ("/srv/ftp/uploads", "public_content_rw_t", "ftpd_t",
             "vsftpd", "write", "file"),
            ("/opt/appdata", "httpd_sys_rw_content_t", "httpd_t",
             "Apache", "write", "dir"),
            ("/srv/samba/docs", "samba_share_t", "smbd_t",
             "Samba", "read", "file"),
        ]

        scenario = random.choice(scenarios)
        self.target_dir = params.get("directory", scenario[0])
        self.correct_type = scenario[1]
        self.service_domain = scenario[2]
        service_name = scenario[3]
        permission = scenario[4]
        obj_class = scenario[5]

        self.description = (
            f"Analyze and resolve an SELinux AVC denial.\n"
            f"\n"
            f"The {service_name} service is being denied '{permission}' access to files\n"
            f"in '{self.target_dir}'. The service runs in the {self.service_domain} domain.\n"
            f"\n"
            f"Tasks:\n"
            f"  1. Use ausearch / audit2why / sealert to identify the root cause\n"
            f"  2. Determine the correct SELinux file type for the target directory\n"
            f"  3. Apply the correct file context to '{self.target_dir}' and all contents\n"
            f"  4. Make the fix persistent\n"
            f"  5. Verify the denial is resolved"
        )

        self.hints = [
            "ausearch -m avc -ts recent | audit2why  — shows the cause and suggests a fix",
            f"Look up what SELinux type {service_name} expects for its content directories",
            "Use semanage fcontext to make context changes persistent, then restorecon to apply",
        ]

        return self

    def validate(self):
        checks = []
        total_points = 0

        # Check 1: Directory exists (3 pts)
        result = execute_safe(["test", "-d", self.target_dir])
        if result.success:
            checks.append(ValidationCheck(
                name="directory_exists",
                passed=True,
                points=3,
                message=f"Directory '{self.target_dir}' exists",
            ))
            total_points += 3
        else:
            checks.append(ValidationCheck(
                name="directory_exists",
                passed=False,
                points=0,
                max_points=3,
                message=f"Directory '{self.target_dir}' not found -- create it first",
            ))
            return ValidationResult(self.id, False, total_points, self.points, checks)

        # Check 2: Current file context (7 pts)
        result = execute_safe(["ls", "-Zd", self.target_dir])
        if result.success and self.correct_type in result.stdout:
            checks.append(ValidationCheck(
                name="current_context",
                passed=True,
                points=7,
                message=f"Directory has correct type: {self.correct_type}",
            ))
            total_points += 7
        else:
            actual = result.stdout.strip() if result.success else "unknown"
            checks.append(ValidationCheck(
                name="current_context",
                passed=False,
                points=0,
                max_points=7,
                message=f"Incorrect context: expected {self.correct_type}, got: {actual}",
            ))

        # Check 3: Persistent fcontext rule (8 pts)
        result = execute_safe(["semanage", "fcontext", "-l"])
        if result.success and self.target_dir in result.stdout and self.correct_type in result.stdout:
            checks.append(ValidationCheck(
                name="persistent_rule",
                passed=True,
                points=8,
                message="Persistent fcontext rule is in place",
            ))
            total_points += 8
        else:
            checks.append(ValidationCheck(
                name="persistent_rule",
                passed=False,
                points=0,
                max_points=8,
                message="No persistent fcontext rule found (use semanage fcontext -a)",
            ))

        passed = total_points >= (self.points * 0.7)
        return ValidationResult(self.id, passed, total_points, self.points, checks)


# ---------------------------------------------------------------------------
# 7. RestoreDefaultContextTask (medium / 8 pts)
# ---------------------------------------------------------------------------
@TaskRegistry.register("selinux")
class RestoreDefaultContextTask(BaseTask):
    """Restore default SELinux contexts with restorecon."""

    def __init__(self):
        super().__init__(
            id="selinux_restorecon_001",
            category="selinux",
            difficulty="medium",
            points=8,
        )
        self.requires_persistence = False
        self.tags = ["selinux", "restorecon", "relabel"]
        self.exam_tips = [
            "restorecon -Rv <path> recursively resets contexts to policy defaults.",
            "Use matchpathcon <path> to see what the default context should be.",
            "Files moved with 'mv' keep their original context -- use restorecon after.",
        ]
        self.directory = None
        self.expected_type = None

    def generate(self, **params):
        dir_options = [
            ("/var/www/html", "httpd_sys_content_t",
             "web content directory -- files were likely moved here with 'mv'"),
            ("/etc/httpd/conf.d", "httpd_config_t",
             "Apache configuration directory"),
            ("/var/log/httpd", "httpd_log_t",
             "Apache log directory"),
            ("/home", "home_root_t",
             "home directory root"),
        ]

        choice = random.choice(dir_options)
        self.directory = params.get("directory", choice[0])
        self.expected_type = choice[1]
        purpose = choice[2]

        self.description = (
            f"Files in '{self.directory}' have incorrect SELinux contexts\n"
            f"(they may have been copied or moved with 'mv').\n"
            f"\n"
            f"  - Restore the default SELinux context on '{self.directory}' recursively\n"
            f"  - The expected type for this path is: {self.expected_type}\n"
            f"\n"
            f"Context: {purpose}"
        )

        self.hints = [
            f"restorecon -Rv {self.directory}",
            f"matchpathcon {self.directory}  -- shows the expected context",
            "restorecon resets to the contexts defined in the policy / file_contexts",
        ]

        return self

    def validate(self):
        checks = []
        total_points = 0

        # Check 1: Directory exists (2 pts)
        result = execute_safe(["test", "-d", self.directory])
        if result.success:
            checks.append(ValidationCheck(
                name="directory_exists",
                passed=True,
                points=2,
                message=f"Directory '{self.directory}' exists",
            ))
            total_points += 2
        else:
            checks.append(ValidationCheck(
                name="directory_exists",
                passed=False,
                points=0,
                max_points=2,
                message=f"Directory '{self.directory}' not found",
            ))
            return ValidationResult(self.id, False, total_points, self.points, checks)

        # Check 2: Context is correct (6 pts)
        result = execute_safe(["ls", "-Zd", self.directory])
        if result.success and self.expected_type in result.stdout:
            checks.append(ValidationCheck(
                name="context_restored",
                passed=True,
                points=6,
                message=f"Context correctly set to {self.expected_type}",
            ))
            total_points += 6
        else:
            actual = result.stdout.strip() if result.success else "unknown"
            checks.append(ValidationCheck(
                name="context_restored",
                passed=False,
                points=0,
                max_points=6,
                message=f"Context not restored: expected {self.expected_type}, got: {actual}",
            ))

        passed = total_points >= (self.points * 0.7)
        return ValidationResult(self.id, passed, total_points, self.points, checks)


# ---------------------------------------------------------------------------
# 9. DiagnoseSELinuxServiceTask (exam / 20 pts) [PERSIST] [EXAM-SEEN]
# ---------------------------------------------------------------------------
@TaskRegistry.register("selinux")
class DiagnoseSELinuxServiceTask(BaseTask):
    """A service fails to start or function due to SELinux -- diagnose and fix."""

    def __init__(self):
        super().__init__(
            id="selinux_service_diag_001",
            category="selinux",
            difficulty="exam",
            points=20,
        )
        self.requires_persistence = True
        self.tags = ["selinux", "troubleshoot", "service", "exam-seen"]
        self.exam_tips = [
            "When a service fails, ALWAYS check: journalctl -xe, ausearch -m avc -ts recent.",
            "Common causes: wrong file context on content dirs, boolean not set, non-standard port.",
            "Fix sequence: identify denial -> determine fix type -> apply fix -> restart service.",
        ]
        self.service = None
        self.fix_steps = []
        self.boolean_name = None
        self.directory = None
        self.context_type = None
        self.port = None
        self.port_type = None

    def generate(self, **params):
        scenarios = [
            {
                "service": "httpd",
                "symptom": "Apache fails to serve content from /srv/website",
                "directory": "/srv/website",
                "context_type": "httpd_sys_content_t",
                "boolean_name": None,
                "port": None,
                "port_type": None,
                "fix_desc": "Set the correct file context on the content directory",
            },
            {
                "service": "httpd",
                "symptom": "Apache starts but cannot connect to a backend database",
                "directory": None,
                "context_type": None,
                "boolean_name": "httpd_can_network_connect",
                "port": None,
                "port_type": None,
                "fix_desc": "Enable the httpd_can_network_connect boolean",
            },
            {
                "service": "httpd",
                "symptom": f"Apache fails to bind to port {random.choice([8080, 8443, 9090])}",
                "directory": None,
                "context_type": None,
                "boolean_name": None,
                "port": None,  # will be set below
                "port_type": "http_port_t",
                "fix_desc": "Add the non-standard port to the http_port_t SELinux type",
            },
            {
                "service": "samba",
                "symptom": "Samba cannot access /srv/samba/data",
                "directory": "/srv/samba/data",
                "context_type": "samba_share_t",
                "boolean_name": None,
                "port": None,
                "port_type": None,
                "fix_desc": "Set the correct file context on the share directory",
            },
        ]

        scenario = random.choice(scenarios)
        self.service = scenario["service"]
        self.directory = params.get("directory", scenario["directory"])
        self.context_type = scenario["context_type"]
        self.boolean_name = scenario["boolean_name"]
        self.port_type = scenario["port_type"]

        # Extract port from symptom if applicable
        if scenario["port"] is None and self.port_type:
            import re
            port_match = re.search(r'port (\d+)', scenario["symptom"])
            self.port = int(port_match.group(1)) if port_match else 8080
        else:
            self.port = scenario["port"]

        symptom = scenario["symptom"]
        fix_desc = scenario["fix_desc"]

        self.description = (
            f"The '{self.service}' service is not functioning correctly due to SELinux.\n"
            f"\n"
            f"Symptom: {symptom}\n"
            f"\n"
            f"Tasks:\n"
            f"  1. Diagnose the SELinux denial (use ausearch, audit2why, sealert, journalctl)\n"
            f"  2. Apply the correct fix: {fix_desc}\n"
            f"  3. Make ALL changes persistent\n"
            f"  4. Verify the service works after the fix"
        )

        self.hints = [
            "ausearch -m avc -ts recent | audit2why",
            "sealert -a /var/log/audit/audit.log",
            "journalctl -xe -u " + self.service,
            "sestatus  -- verify SELinux is enforcing",
        ]
        if self.directory and self.context_type:
            self.hints.append(f"File context fix: semanage fcontext then restorecon to apply")
        if self.boolean_name:
            self.hints.append("Boolean fix: setsebool -P <boolean> on/off")
        if self.port and self.port_type:
            self.hints.append(f"Port fix: semanage port -a -t <type> -p <protocol> <port>")

        return self

    def validate(self):
        checks = []
        total_points = 0
        max_per_check = self._calculate_check_weights()

        # Check fcontext fix if applicable
        if self.directory and self.context_type:
            # Directory exists
            result = execute_safe(["test", "-d", self.directory])
            if result.success:
                checks.append(ValidationCheck(
                    name="directory_exists",
                    passed=True,
                    points=2,
                    message=f"Directory '{self.directory}' exists",
                ))
                total_points += 2
            else:
                checks.append(ValidationCheck(
                    name="directory_exists",
                    passed=False,
                    points=0,
                    max_points=2,
                    message=f"Directory '{self.directory}' not found",
                ))

            # Current context
            result = execute_safe(["ls", "-Zd", self.directory])
            ctx_pts = max_per_check
            if result.success and self.context_type in result.stdout:
                checks.append(ValidationCheck(
                    name="file_context",
                    passed=True,
                    points=ctx_pts,
                    message=f"File context is {self.context_type}",
                ))
                total_points += ctx_pts
            else:
                checks.append(ValidationCheck(
                    name="file_context",
                    passed=False,
                    points=0,
                    max_points=ctx_pts,
                    message=f"Incorrect file context on {self.directory}",
                ))

            # Persistent fcontext
            result = execute_safe(["semanage", "fcontext", "-l"])
            if result.success and self.directory in result.stdout and self.context_type in result.stdout:
                checks.append(ValidationCheck(
                    name="persistent_fcontext",
                    passed=True,
                    points=max_per_check,
                    message="Persistent fcontext rule in place",
                ))
                total_points += max_per_check
            else:
                checks.append(ValidationCheck(
                    name="persistent_fcontext",
                    passed=False,
                    points=0,
                    max_points=max_per_check,
                    message="No persistent fcontext rule found",
                ))

        # Check boolean fix if applicable
        if self.boolean_name:
            result = execute_safe(["getsebool", self.boolean_name])
            bool_pts = max_per_check
            if result.success and "--> on" in result.stdout:
                checks.append(ValidationCheck(
                    name="boolean_set",
                    passed=True,
                    points=bool_pts,
                    message=f"Boolean '{self.boolean_name}' is on",
                ))
                total_points += bool_pts
            else:
                checks.append(ValidationCheck(
                    name="boolean_set",
                    passed=False,
                    points=0,
                    max_points=bool_pts,
                    message=f"Boolean '{self.boolean_name}' is not on",
                ))

            # Check persistence
            result = execute_safe(["semanage", "boolean", "-l"])
            if result.success:
                persistent = False
                for line in result.stdout.splitlines():
                    if self.boolean_name in line and "(on" in line.replace(" ", ""):
                        persistent = True
                        break
                if persistent:
                    checks.append(ValidationCheck(
                        name="boolean_persistent",
                        passed=True,
                        points=max_per_check,
                        message="Boolean persistently enabled",
                    ))
                    total_points += max_per_check
                else:
                    checks.append(ValidationCheck(
                        name="boolean_persistent",
                        passed=False,
                        points=0,
                        max_points=max_per_check,
                        message="Boolean not persistently set",
                    ))
            else:
                checks.append(ValidationCheck(
                    name="boolean_persistent",
                    passed=False,
                    points=0,
                    max_points=max_per_check,
                    message="Could not verify boolean persistence",
                ))

        # Check port fix if applicable
        if self.port and self.port_type:
            result = execute_safe(["semanage", "port", "-l"])
            port_pts = max_per_check * 2
            if result.success:
                found = False
                for line in result.stdout.splitlines():
                    if self.port_type in line and str(self.port) in line:
                        found = True
                        break
                if found:
                    checks.append(ValidationCheck(
                        name="port_context",
                        passed=True,
                        points=port_pts,
                        message=f"Port {self.port} assigned to {self.port_type}",
                    ))
                    total_points += port_pts
                else:
                    checks.append(ValidationCheck(
                        name="port_context",
                        passed=False,
                        points=0,
                        max_points=port_pts,
                        message=f"Port {self.port} not assigned to {self.port_type}",
                    ))
            else:
                checks.append(ValidationCheck(
                    name="port_context",
                    passed=False,
                    points=0,
                    max_points=port_pts,
                    message="Could not query SELinux port contexts",
                ))

        # Check service is running
        result = execute_safe(["systemctl", "is-active", self.service])
        svc_pts = 2
        if result.success and result.stdout.strip() == "active":
            checks.append(ValidationCheck(
                name="service_running",
                passed=True,
                points=svc_pts,
                message=f"Service '{self.service}' is running",
            ))
            total_points += svc_pts
        else:
            checks.append(ValidationCheck(
                name="service_running",
                passed=False,
                points=0,
                max_points=svc_pts,
                message=f"Service '{self.service}' is not running",
                details="Start the service after fixing SELinux: systemctl restart " + self.service,
            ))

        passed = total_points >= (self.points * 0.7)
        return ValidationResult(self.id, passed, total_points, self.points, checks)

    def _calculate_check_weights(self):
        """Calculate per-check point weight based on active fix types."""
        num_fix_types = 0
        if self.directory and self.context_type:
            num_fix_types += 2  # context + persistent
        if self.boolean_name:
            num_fix_types += 2  # boolean + persistent
        if self.port and self.port_type:
            num_fix_types += 1  # port (counted as 2x weight internally)
        # Reserve 4 pts for dir-exists + service-running; distribute rest
        remaining = self.points - 4
        if num_fix_types == 0:
            return remaining
        return max(1, remaining // num_fix_types)


# ---------------------------------------------------------------------------
# 10. SELinuxRelabelTask (easy / 5 pts)
# ---------------------------------------------------------------------------
@TaskRegistry.register("selinux")
class SELinuxRelabelTask(BaseTask):
    """Trigger a full filesystem relabel on next boot."""

    def __init__(self):
        super().__init__(
            id="selinux_relabel_001",
            category="selinux",
            difficulty="easy",
            points=5,
        )
        self.requires_persistence = False
        self.tags = ["selinux", "relabel", "autorelabel"]
        self.exam_tips = [
            "touch /.autorelabel && reboot  triggers a full relabel.",
            "fixfiles -F onboot  also schedules a relabel.",
            "A relabel can take a LONG time on large filesystems.",
            "This is needed when switching from disabled to enforcing.",
        ]

    def generate(self, **params):
        self.description = (
            "Schedule a full SELinux filesystem relabel on the next reboot:\n"
            "\n"
            "  1. Create the file that triggers automatic relabeling\n"
            "  2. The system will relabel all files on the next boot\n"
            "\n"
            "This is commonly needed after changing SELinux from disabled to\n"
            "enforcing mode, or after significant policy changes."
        )

        self.hints = [
            "touch /.autorelabel",
            "Alternative: fixfiles -F onboot",
            "The /.autorelabel file signals init to run a full relabel",
            "Verify: ls -la /.autorelabel",
        ]

        return self

    def validate(self):
        checks = []
        total_points = 0

        # Check 1: /.autorelabel file exists (5 pts)
        result = execute_safe(["test", "-f", "/.autorelabel"])
        if result.success:
            checks.append(ValidationCheck(
                name="autorelabel_file",
                passed=True,
                points=5,
                message="/.autorelabel file exists -- relabel scheduled for next boot",
            ))
            total_points += 5
        else:
            checks.append(ValidationCheck(
                name="autorelabel_file",
                passed=False,
                points=0,
                max_points=5,
                message="/.autorelabel file not found (use 'touch /.autorelabel')",
            ))

        passed = total_points >= (self.points * 0.7)
        return ValidationResult(self.id, passed, total_points, self.points, checks)
