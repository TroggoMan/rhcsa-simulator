"""
Repository management tasks for RHCSA EX200 v10 exam.
Covers configuring, enabling, disabling, and troubleshooting DNF repositories.
"""

import random
import re
import logging
from tasks.base import BaseTask
from tasks.registry import TaskRegistry
from core.validator import ValidationCheck, ValidationResult
from validators.safe_executor import execute_safe


logger = logging.getLogger(__name__)


# Real, reachable RHEL 10-compatible repositories. Every base_url was verified
# to serve repodata/repomd.xml and every gpg_key_url to return 200 (2026-06).
#
# Why real URLs instead of http://content.example.com/... : an *enabled* repo
# whose baseurl can't be reached makes EVERY subsequent `dnf` operation fail
# ("Failed to download metadata for repo ..."), so configuring a fake repo
# would silently break the package-install tasks elsewhere in the exam. With
# real mirrors the repo the candidate configures actually works and `dnf
# repolist` / `dnf install` keep functioning. Tasks cycle through this pool.
#
# gpg_key_url is None where no stable key URL was verified; those entries are
# used only for gpgcheck=0 scenarios.
REAL_REPOS = [
    {'repo_id': 'rocky10-baseos', 'repo_name': 'Rocky Linux 10 - BaseOS',
     'base_url': 'https://dl.rockylinux.org/pub/rocky/10/BaseOS/x86_64/os/',
     'gpg_key_url': 'https://dl.rockylinux.org/pub/rocky/RPM-GPG-KEY-Rocky-10'},
    {'repo_id': 'rocky10-appstream', 'repo_name': 'Rocky Linux 10 - AppStream',
     'base_url': 'https://dl.rockylinux.org/pub/rocky/10/AppStream/x86_64/os/',
     'gpg_key_url': 'https://dl.rockylinux.org/pub/rocky/RPM-GPG-KEY-Rocky-10'},
    {'repo_id': 'rocky10-crb', 'repo_name': 'Rocky Linux 10 - CRB',
     'base_url': 'https://dl.rockylinux.org/pub/rocky/10/CRB/x86_64/os/',
     'gpg_key_url': 'https://dl.rockylinux.org/pub/rocky/RPM-GPG-KEY-Rocky-10'},
    {'repo_id': 'rocky10-extras', 'repo_name': 'Rocky Linux 10 - Extras',
     'base_url': 'https://dl.rockylinux.org/pub/rocky/10/extras/x86_64/os/',
     'gpg_key_url': 'https://dl.rockylinux.org/pub/rocky/RPM-GPG-KEY-Rocky-10'},
    {'repo_id': 'rocky10-devel', 'repo_name': 'Rocky Linux 10 - Devel',
     'base_url': 'https://dl.rockylinux.org/pub/rocky/10/devel/x86_64/os/',
     'gpg_key_url': 'https://dl.rockylinux.org/pub/rocky/RPM-GPG-KEY-Rocky-10'},
    {'repo_id': 'alma10-baseos', 'repo_name': 'AlmaLinux 10 - BaseOS',
     'base_url': 'https://repo.almalinux.org/almalinux/10/BaseOS/x86_64/os/',
     'gpg_key_url': 'https://repo.almalinux.org/almalinux/RPM-GPG-KEY-AlmaLinux-10'},
    {'repo_id': 'alma10-appstream', 'repo_name': 'AlmaLinux 10 - AppStream',
     'base_url': 'https://repo.almalinux.org/almalinux/10/AppStream/x86_64/os/',
     'gpg_key_url': 'https://repo.almalinux.org/almalinux/RPM-GPG-KEY-AlmaLinux-10'},
    {'repo_id': 'alma10-crb', 'repo_name': 'AlmaLinux 10 - CRB',
     'base_url': 'https://repo.almalinux.org/almalinux/10/CRB/x86_64/os/',
     'gpg_key_url': 'https://repo.almalinux.org/almalinux/RPM-GPG-KEY-AlmaLinux-10'},
    {'repo_id': 'alma10-extras', 'repo_name': 'AlmaLinux 10 - Extras',
     'base_url': 'https://repo.almalinux.org/almalinux/10/extras/x86_64/os/',
     'gpg_key_url': 'https://repo.almalinux.org/almalinux/RPM-GPG-KEY-AlmaLinux-10'},
    {'repo_id': 'epel', 'repo_name': 'Extra Packages for Enterprise Linux 10',
     'base_url': 'https://dl.fedoraproject.org/pub/epel/10/Everything/x86_64/',
     'gpg_key_url': 'https://dl.fedoraproject.org/pub/epel/RPM-GPG-KEY-EPEL-10'},
    {'repo_id': 'epel9', 'repo_name': 'Extra Packages for Enterprise Linux 9',
     'base_url': 'https://dl.fedoraproject.org/pub/epel/9/Everything/x86_64/',
     'gpg_key_url': 'https://dl.fedoraproject.org/pub/epel/RPM-GPG-KEY-EPEL-9'},
    {'repo_id': 'grafana', 'repo_name': 'Grafana OSS',
     'base_url': 'https://rpm.grafana.com/',
     'gpg_key_url': 'https://rpm.grafana.com/gpg.key'},
    {'repo_id': 'nodesource-nodejs', 'repo_name': 'Node.js 22.x',
     'base_url': 'https://rpm.nodesource.com/pub_22.x/nodistro/nodejs/x86_64/',
     'gpg_key_url': None},
    {'repo_id': 'vscode', 'repo_name': 'Visual Studio Code',
     'base_url': 'https://packages.microsoft.com/yumrepos/vscode/',
     'gpg_key_url': 'https://packages.microsoft.com/keys/microsoft.asc'},
    {'repo_id': 'kubernetes', 'repo_name': 'Kubernetes v1.31',
     'base_url': 'https://pkgs.k8s.io/core:/stable:/v1.31/rpm/',
     'gpg_key_url': 'https://pkgs.k8s.io/core:/stable:/v1.31/rpm/repodata/repomd.xml.key'},
    {'repo_id': 'hashicorp', 'repo_name': 'HashiCorp Stable',
     'base_url': 'https://rpm.releases.hashicorp.com/RHEL/10/x86_64/stable/',
     'gpg_key_url': 'https://rpm.releases.hashicorp.com/gpg'},
    {'repo_id': 'docker-ce', 'repo_name': 'Docker CE Stable',
     'base_url': 'https://download.docker.com/linux/rhel/10/x86_64/stable/',
     'gpg_key_url': 'https://download.docker.com/linux/rhel/gpg'},
    {'repo_id': 'elrepo', 'repo_name': 'ELRepo.org Community Enterprise Linux Repository',
     'base_url': 'https://elrepo.org/linux/elrepo/el10/x86_64/',
     'gpg_key_url': 'https://www.elrepo.org/RPM-GPG-KEY-elrepo.org'},
    {'repo_id': 'rpmfusion-free', 'repo_name': 'RPM Fusion Free Updates',
     'base_url': 'https://download1.rpmfusion.org/free/el/updates/10/x86_64/',
     'gpg_key_url': None},
    {'repo_id': 'pgdg17', 'repo_name': 'PostgreSQL 17 for RHEL 10',
     'base_url': 'https://download.postgresql.org/pub/repos/yum/17/redhat/rhel-10-x86_64/',
     'gpg_key_url': None},
    {'repo_id': 'mariadb', 'repo_name': 'MariaDB 11.4',
     'base_url': 'https://yum.mariadb.org/11.4/rhel/10/x86_64/',
     'gpg_key_url': 'https://yum.mariadb.org/RPM-GPG-KEY-MariaDB'},
    {'repo_id': 'nginx', 'repo_name': 'nginx stable',
     'base_url': 'https://nginx.org/packages/rhel/10/x86_64/',
     'gpg_key_url': 'https://nginx.org/keys/nginx_signing.key'},
    {'repo_id': 'tailscale', 'repo_name': 'Tailscale Stable',
     'base_url': 'https://pkgs.tailscale.com/stable/rhel/10/x86_64/',
     'gpg_key_url': 'https://pkgs.tailscale.com/stable/rhel/10/repo.gpg'},
    {'repo_id': 'packages-microsoft-com-prod', 'repo_name': 'Microsoft Production',
     'base_url': 'https://packages.microsoft.com/rhel/10/prod/',
     'gpg_key_url': 'https://packages.microsoft.com/keys/microsoft.asc'},
    {'repo_id': 'google-cloud-cli', 'repo_name': 'Google Cloud CLI',
     'base_url': 'https://packages.cloud.google.com/yum/repos/cloud-sdk-el9-x86_64/',
     'gpg_key_url': 'https://packages.cloud.google.com/yum/doc/yum-key.gpg'},
]

# Subset that has a verified GPG key, for tasks that require gpgcheck=1 + gpgkey.
REAL_REPOS_WITH_GPG = [r for r in REAL_REPOS if r.get('gpg_key_url')]


@TaskRegistry.register("repos")
class ConfigureRepoTask(BaseTask):
    """Configure a new DNF repository with baseurl and gpgcheck."""

    def __init__(self):
        super().__init__(
            id="repo_configure_001",
            category="repos",
            difficulty="exam",
            points=10
        )
        self.requires_persistence = True
        self.tags = []
        self.exam_tips = [
            "Use /etc/yum.repos.d/ for repo files",
            "Repo file must end in .repo extension",
            "Required fields: [repoid], name, baseurl, enabled, gpgcheck",
            "dnf repolist to verify the repo is visible"
        ]
        self.repo_id = None
        self.repo_name = None
        self.base_url = None
        self.gpgcheck = None

    def generate(self, **params):
        """Generate a repository configuration task using a real, reachable repo
        drawn from REAL_REPOS so the configured repo actually works and does not
        break dnf for other tasks."""
        config = params.get('config', random.choice(REAL_REPOS))
        self.repo_id = config['repo_id']
        self.repo_name = config['repo_name']
        self.base_url = config['base_url']
        self.gpgcheck = params.get('gpgcheck', random.choice([0, 0, 0, 1]))

        self.description = (
            f"Configure a DNF repository:\n"
            f"  - Repository ID: {self.repo_id}\n"
            f"  - Repository name: {self.repo_name}\n"
            f"  - Base URL: {self.base_url}\n"
            f"  - GPG check: {'enabled (gpgcheck=1)' if self.gpgcheck else 'disabled (gpgcheck=0)'}\n"
            f"  - Repository must be enabled\n"
            f"  - Create the file: /etc/yum.repos.d/{self.repo_id}.repo"
        )

        self.hints = [
            f"Repo files go in /etc/yum.repos.d/ and must end in .repo",
            f"Every repo file needs: [repoid], name=, baseurl=, enabled=, gpgcheck=",
            "Verify with: dnf repolist",
        ]

        return self

    def validate(self):
        """Validate repository configuration by checking file and repo visibility."""
        checks = []
        total_points = 0
        repo_file = f'/etc/yum.repos.d/{self.repo_id}.repo'

        # Check 1: Repo file exists (3 points)
        result = execute_safe(['test', '-f', repo_file])
        file_exists = result.success
        if file_exists:
            checks.append(ValidationCheck(
                name="repo_file_exists",
                passed=True,
                points=3,
                message=f"Repository file {repo_file} exists"
            ))
            total_points += 3
        else:
            checks.append(ValidationCheck(
                name="repo_file_exists",
                passed=False,
                points=0,
                max_points=3,
                message=f"Repository file {repo_file} not found"
            ))
            passed = False
            return ValidationResult(self.id, passed, total_points, self.points, checks)

        # Check 2: Repo section header present (2 points)
        result = execute_safe(['grep', '-c', f'\\[{self.repo_id}\\]', repo_file])
        if result.success and result.stdout.strip() != '0':
            checks.append(ValidationCheck(
                name="repo_section_header",
                passed=True,
                points=2,
                message=f"Repository section [{self.repo_id}] found"
            ))
            total_points += 2
        else:
            checks.append(ValidationCheck(
                name="repo_section_header",
                passed=False,
                points=0,
                max_points=2,
                message=f"Repository section [{self.repo_id}] not found in file"
            ))

        # Check 3: baseurl is configured correctly (3 points)
        # dnf's .repo files are parsed as INI (configparser), which allows
        # optional whitespace around "=" (e.g. "baseurl = <url>"). Match that
        # with -E and tolerate whitespace instead of requiring "baseurl=<url>"
        # verbatim.
        result = execute_safe(['grep', '-c', '-E', f'baseurl[ \\t]*=[ \\t]*{re.escape(self.base_url)}', repo_file])
        if result.success and result.stdout.strip() != '0':
            checks.append(ValidationCheck(
                name="baseurl_configured",
                passed=True,
                points=3,
                message=f"Base URL is correctly configured"
            ))
            total_points += 3
        else:
            # Partial credit if baseurl line exists but different URL
            result2 = execute_safe(['grep', '-c', '-E', 'baseurl[ \\t]*=', repo_file])
            if result2.success and result2.stdout.strip() != '0':
                checks.append(ValidationCheck(
                    name="baseurl_configured",
                    passed=False,
                    points=1,
                    max_points=3,
                    message="baseurl present but URL does not match expected value"
                ))
                total_points += 1
            else:
                checks.append(ValidationCheck(
                    name="baseurl_configured",
                    passed=False,
                    points=0,
                    max_points=3,
                    message="baseurl not found in repository file"
                ))

        # Check 4: gpgcheck setting (2 points)
        result = execute_safe(['grep', '-c', '-E', f'gpgcheck[ \\t]*=[ \\t]*{self.gpgcheck}', repo_file])
        if result.success and result.stdout.strip() != '0':
            checks.append(ValidationCheck(
                name="gpgcheck_setting",
                passed=True,
                points=2,
                message=f"gpgcheck={self.gpgcheck} is correctly set"
            ))
            total_points += 2
        else:
            checks.append(ValidationCheck(
                name="gpgcheck_setting",
                passed=False,
                points=0,
                max_points=2,
                message=f"gpgcheck={self.gpgcheck} not found in repository file"
            ))

        passed = total_points >= (self.points * 0.7)
        return ValidationResult(self.id, passed, total_points, self.points, checks)


@TaskRegistry.register("repos")
class ConfigureRepoGPGTask(BaseTask):
    """Configure a DNF repository with GPG key verification."""

    def __init__(self):
        super().__init__(
            id="repo_gpg_001",
            category="repos",
            difficulty="exam",
            points=12
        )
        self.requires_persistence = True
        self.tags = []
        self.exam_tips = [
            "GPG key URL uses gpgkey= directive in .repo file",
            "gpgcheck=1 must be set to enforce GPG checking",
            "Import GPG key with: rpm --import <key_url>",
            "Keys are stored in /etc/pki/rpm-gpg/"
        ]
        self.repo_id = None
        self.repo_name = None
        self.base_url = None
        self.gpg_key_url = None

    def generate(self, **params):
        """Generate a repository + GPG key task using a real, reachable repo
        (and real key URL) drawn from REAL_REPOS_WITH_GPG."""
        config = params.get('config', random.choice(REAL_REPOS_WITH_GPG))
        self.repo_id = config['repo_id']
        self.repo_name = config['repo_name']
        self.base_url = config['base_url']
        self.gpg_key_url = config['gpg_key_url']

        self.description = (
            f"Configure a DNF repository with GPG key verification:\n"
            f"  - Repository ID: {self.repo_id}\n"
            f"  - Repository name: {self.repo_name}\n"
            f"  - Base URL: {self.base_url}\n"
            f"  - GPG key URL: {self.gpg_key_url}\n"
            f"  - GPG checking must be enabled (gpgcheck=1)\n"
            f"  - The repository must be enabled\n"
            f"  - Create the file: /etc/yum.repos.d/{self.repo_id}.repo"
        )

        self.hints = [
            f"Create /etc/yum.repos.d/{self.repo_id}.repo with gpgcheck=1 and gpgkey={self.gpg_key_url}",
            f"File format:\n[{self.repo_id}]\nname={self.repo_name}\n"
            f"baseurl={self.base_url}\nenabled=1\ngpgcheck=1\ngpgkey={self.gpg_key_url}",
            "You may also need to import the GPG key: rpm --import <key_url>",
            "Verify with: dnf repolist -v",
        ]

        return self

    def validate(self):
        """Validate repository with GPG key configuration."""
        checks = []
        total_points = 0
        repo_file = f'/etc/yum.repos.d/{self.repo_id}.repo'

        # Check 1: Repo file exists (2 points)
        result = execute_safe(['test', '-f', repo_file])
        if result.success:
            checks.append(ValidationCheck(
                name="repo_file_exists",
                passed=True,
                points=2,
                message=f"Repository file {repo_file} exists"
            ))
            total_points += 2
        else:
            checks.append(ValidationCheck(
                name="repo_file_exists",
                passed=False,
                points=0,
                max_points=2,
                message=f"Repository file {repo_file} not found"
            ))
            passed = False
            return ValidationResult(self.id, passed, total_points, self.points, checks)

        # Check 2: Repo section header (2 points)
        result = execute_safe(['grep', '-c', f'\\[{self.repo_id}\\]', repo_file])
        if result.success and result.stdout.strip() != '0':
            checks.append(ValidationCheck(
                name="repo_section",
                passed=True,
                points=2,
                message=f"Repository section [{self.repo_id}] present"
            ))
            total_points += 2
        else:
            checks.append(ValidationCheck(
                name="repo_section",
                passed=False,
                points=0,
                max_points=2,
                message=f"Section [{self.repo_id}] missing"
            ))

        # Check 3: baseurl configured (3 points)
        # dnf's .repo files are parsed as INI (configparser), which allows
        # optional whitespace around "=" (e.g. "baseurl = <url>"). Match that
        # with -E and tolerate whitespace instead of requiring "baseurl=<url>"
        # verbatim.
        result = execute_safe(['grep', '-c', '-E', f'baseurl[ \\t]*=[ \\t]*{re.escape(self.base_url)}', repo_file])
        if result.success and result.stdout.strip() != '0':
            checks.append(ValidationCheck(
                name="baseurl_correct",
                passed=True,
                points=3,
                message="Base URL correctly configured"
            ))
            total_points += 3
        else:
            checks.append(ValidationCheck(
                name="baseurl_correct",
                passed=False,
                points=0,
                max_points=3,
                message="Base URL not correctly configured"
            ))

        # Check 4: gpgcheck=1 (2 points)
        result = execute_safe(['grep', '-c', '-E', 'gpgcheck[ \\t]*=[ \\t]*1', repo_file])
        if result.success and result.stdout.strip() != '0':
            checks.append(ValidationCheck(
                name="gpgcheck_enabled",
                passed=True,
                points=2,
                message="GPG checking is enabled (gpgcheck=1)"
            ))
            total_points += 2
        else:
            checks.append(ValidationCheck(
                name="gpgcheck_enabled",
                passed=False,
                points=0,
                max_points=2,
                message="gpgcheck=1 not found; GPG checking is not enabled"
            ))

        # Check 5: gpgkey directive present (3 points)
        result = execute_safe(['grep', '-c', '-E', f'gpgkey[ \\t]*=[ \\t]*{re.escape(self.gpg_key_url)}', repo_file])
        if result.success and result.stdout.strip() != '0':
            checks.append(ValidationCheck(
                name="gpgkey_configured",
                passed=True,
                points=3,
                message=f"GPG key URL correctly configured"
            ))
            total_points += 3
        else:
            # Partial credit if gpgkey line exists but wrong URL
            result2 = execute_safe(['grep', '-c', '-E', 'gpgkey[ \\t]*=', repo_file])
            if result2.success and result2.stdout.strip() != '0':
                checks.append(ValidationCheck(
                    name="gpgkey_configured",
                    passed=False,
                    points=1,
                    max_points=3,
                    message="gpgkey directive present but URL does not match"
                ))
                total_points += 1
            else:
                checks.append(ValidationCheck(
                    name="gpgkey_configured",
                    passed=False,
                    points=0,
                    max_points=3,
                    message="gpgkey directive not found in repo file"
                ))

        passed = total_points >= (self.points * 0.7)
        return ValidationResult(self.id, passed, total_points, self.points, checks)


@TaskRegistry.register("repos")
class EnableDisableRepoTask(BaseTask):
    """Enable or disable a specific repository."""

    def __init__(self):
        super().__init__(
            id="repo_enable_disable_001",
            category="repos",
            difficulty="easy",
            points=6
        )
        self.requires_persistence = True
        self.tags = []
        self.exam_tips = [
            "dnf config-manager --enable/--disable <repo>",
            "Or manually edit /etc/yum.repos.d/<repo>.repo and set enabled=0 or enabled=1",
            "dnf repolist all shows both enabled and disabled repos"
        ]
        self.repo_name = None
        self.action = None

    def generate(self, **params):
        """Generate enable/disable repository task."""
        repos = [
            'epel', 'crb', 'baseos', 'appstream',
            'rhel-10-for-x86_64-baseos-rpms',
            'rhel-10-for-x86_64-appstream-rpms',
        ]
        self.repo_name = params.get('repo', random.choice(repos))
        self.action = params.get('action', random.choice(['enable', 'disable']))

        action_word = 'Enable' if self.action == 'enable' else 'Disable'

        self.description = (
            f"{action_word} a package repository:\n"
            f"  - Repository: {self.repo_name}\n"
            f"  - Action: {self.action}\n"
            f"  - Ensure the change is persistent across reboots"
        )

        self.hints = [
            f"dnf config-manager --set-{self.action}d {self.repo_name}",
            f"Or: edit /etc/yum.repos.d/ file and set enabled={'1' if self.action == 'enable' else '0'}",
            "List all repos: dnf repolist all",
            "Check specific repo: dnf repoinfo <repo>",
        ]

        return self

    def validate(self):
        """Validate repository enable/disable state."""
        checks = []
        total_points = 0

        result = execute_safe(['dnf', 'repolist', 'all'])
        if not result.success:
            checks.append(ValidationCheck(
                name="repo_check",
                passed=False,
                points=0,
                max_points=6,
                message="Could not query repository list"
            ))
            return ValidationResult(self.id, False, 0, self.points, checks)

        found = False
        for line in result.stdout.splitlines():
            if self.repo_name in line.lower():
                found = True
                if self.action == 'enable' and 'enabled' in line.lower():
                    checks.append(ValidationCheck(
                        name="repo_state",
                        passed=True,
                        points=6,
                        message=f"Repository {self.repo_name} is enabled"
                    ))
                    total_points += 6
                elif self.action == 'disable' and 'disabled' in line.lower():
                    checks.append(ValidationCheck(
                        name="repo_state",
                        passed=True,
                        points=6,
                        message=f"Repository {self.repo_name} is disabled"
                    ))
                    total_points += 6
                else:
                    checks.append(ValidationCheck(
                        name="repo_state",
                        passed=False,
                        points=0,
                        max_points=6,
                        message=f"Repository {self.repo_name} is not in the expected '{self.action}d' state"
                    ))
                break

        if not found:
            checks.append(ValidationCheck(
                name="repo_state",
                passed=False,
                points=0,
                max_points=6,
                message=f"Repository {self.repo_name} not found in repolist output"
            ))

        passed = total_points >= (self.points * 0.7)
        return ValidationResult(self.id, passed, total_points, self.points, checks)


@TaskRegistry.register("repos")
class ConfigureBaseOSAppStreamTask(BaseTask):
    """Configure both BaseOS and AppStream repositories - commonly seen on real exam."""

    def __init__(self):
        super().__init__(
            id="repo_baseos_appstream_001",
            category="repos",
            difficulty="exam",
            points=15
        )
        self.requires_persistence = True
        self.tags = ['exam-seen']
        self.exam_tips = [
            "The exam typically provides a URL for a content server",
            "You need BOTH BaseOS and AppStream repos configured",
            "Without these repos, you cannot install packages for other tasks",
            "Configure repos FIRST on the exam before attempting other tasks",
            "Common format: <server>/BaseOS/<arch>/os/ and <server>/AppStream/<arch>/os/",
        ]
        self.server_url = None
        self.baseos_url = None
        self.appstream_url = None
        self.baseos_repo_id = None
        self.appstream_repo_id = None

    def generate(self, **params):
        """Generate BaseOS + AppStream repository configuration task."""
        # Real distro mirror roots whose /<repo>/x86_64/os/ trees exist, so the
        # configured repos actually resolve and `dnf repolist` shows them.
        servers = [
            'https://dl.rockylinux.org/pub/rocky/10',
            'https://repo.almalinux.org/almalinux/10',
        ]

        self.server_url = params.get('server_url', random.choice(servers))
        self.baseos_url = f"{self.server_url}/BaseOS/x86_64/os/"
        self.appstream_url = f"{self.server_url}/AppStream/x86_64/os/"

        # No 'rhel-*' names here: Reset Machine deliberately preserves repo
        # files with the rhel-/redhat- system prefixes, so a task-created
        # rhel-baseos.repo would survive every reset.
        repo_id_sets = [
            ('baseos', 'appstream'),
            ('lab-baseos', 'lab-appstream'),
            ('BaseOS', 'AppStream'),
            ('local-baseos', 'local-appstream'),
        ]
        repo_ids = params.get('repo_ids', random.choice(repo_id_sets))
        self.baseos_repo_id = repo_ids[0]
        self.appstream_repo_id = repo_ids[1]

        self.description = (
            f"Configure both BaseOS and AppStream repositories:\n"
            f"  - Content server: {self.server_url}\n"
            f"  - BaseOS repo ID: {self.baseos_repo_id}\n"
            f"    BaseOS URL: {self.baseos_url}\n"
            f"  - AppStream repo ID: {self.appstream_repo_id}\n"
            f"    AppStream URL: {self.appstream_url}\n"
            f"  - Both repositories must be enabled\n"
            f"  - GPG check should be disabled for both\n"
            f"  - Create repo files in /etc/yum.repos.d/"
        )

        self.hints = [
            "You can put both repos in one file or create separate .repo files",
            f"File: /etc/yum.repos.d/{self.baseos_repo_id}.repo with baseurl={self.baseos_url}",
            f"File: /etc/yum.repos.d/{self.appstream_repo_id}.repo with baseurl={self.appstream_url}",
            "Each section needs: [repoid], name, baseurl, enabled=1, gpgcheck=0",
            "Verify both: dnf repolist",
        ]

        return self

    def validate(self):
        """Validate both BaseOS and AppStream repositories are configured."""
        checks = []
        total_points = 0

        # Validate BaseOS repo
        baseos_file_found = False
        # Check common file locations
        for fname in [f'{self.baseos_repo_id}.repo', 'local.repo', 'rhel.repo',
                      'baseos.repo', 'BaseOS.repo', 'exam.repo']:
            repo_path = f'/etc/yum.repos.d/{fname}'
            result = execute_safe(['grep', '-l', f'\\[{self.baseos_repo_id}\\]', repo_path])
            if result.success:
                baseos_file_found = True
                break

        if not baseos_file_found:
            # Broader search in all .repo files
            result = execute_safe(['grep', '-rl', self.baseos_url, '/etc/yum.repos.d/'])
            if result.success and result.stdout.strip():
                baseos_file_found = True

        # Check 1: BaseOS repo file exists (3 points)
        if baseos_file_found:
            checks.append(ValidationCheck(
                name="baseos_repo_file",
                passed=True,
                points=3,
                message="BaseOS repository file found"
            ))
            total_points += 3
        else:
            checks.append(ValidationCheck(
                name="baseos_repo_file",
                passed=False,
                points=0,
                max_points=3,
                message="BaseOS repository file not found in /etc/yum.repos.d/"
            ))

        # Check 2: BaseOS baseurl correct (3 points)
        result = execute_safe(['grep', '-r', self.baseos_url, '/etc/yum.repos.d/'])
        if result.success and self.baseos_url in result.stdout:
            checks.append(ValidationCheck(
                name="baseos_baseurl",
                passed=True,
                points=3,
                message=f"BaseOS baseurl correctly configured"
            ))
            total_points += 3
        else:
            checks.append(ValidationCheck(
                name="baseos_baseurl",
                passed=False,
                points=0,
                max_points=3,
                message=f"BaseOS baseurl ({self.baseos_url}) not found"
            ))

        # Validate AppStream repo
        appstream_file_found = False
        for fname in [f'{self.appstream_repo_id}.repo', 'local.repo', 'rhel.repo',
                      'appstream.repo', 'AppStream.repo', 'exam.repo']:
            repo_path = f'/etc/yum.repos.d/{fname}'
            result = execute_safe(['grep', '-l', f'\\[{self.appstream_repo_id}\\]', repo_path])
            if result.success:
                appstream_file_found = True
                break

        if not appstream_file_found:
            result = execute_safe(['grep', '-rl', self.appstream_url, '/etc/yum.repos.d/'])
            if result.success and result.stdout.strip():
                appstream_file_found = True

        # Check 3: AppStream repo file exists (3 points)
        if appstream_file_found:
            checks.append(ValidationCheck(
                name="appstream_repo_file",
                passed=True,
                points=3,
                message="AppStream repository file found"
            ))
            total_points += 3
        else:
            checks.append(ValidationCheck(
                name="appstream_repo_file",
                passed=False,
                points=0,
                max_points=3,
                message="AppStream repository file not found in /etc/yum.repos.d/"
            ))

        # Check 4: AppStream baseurl correct (3 points)
        result = execute_safe(['grep', '-r', self.appstream_url, '/etc/yum.repos.d/'])
        if result.success and self.appstream_url in result.stdout:
            checks.append(ValidationCheck(
                name="appstream_baseurl",
                passed=True,
                points=3,
                message="AppStream baseurl correctly configured"
            ))
            total_points += 3
        else:
            checks.append(ValidationCheck(
                name="appstream_baseurl",
                passed=False,
                points=0,
                max_points=3,
                message=f"AppStream baseurl ({self.appstream_url}) not found"
            ))

        # Check 5: Both repos visible in dnf repolist (3 points)
        result = execute_safe(['dnf', 'repolist'])
        if result.success:
            stdout_lower = result.stdout.lower()
            baseos_visible = (self.baseos_repo_id.lower() in stdout_lower or
                              'baseos' in stdout_lower)
            appstream_visible = (self.appstream_repo_id.lower() in stdout_lower or
                                 'appstream' in stdout_lower)
            if baseos_visible and appstream_visible:
                checks.append(ValidationCheck(
                    name="repos_visible",
                    passed=True,
                    points=3,
                    message="Both BaseOS and AppStream repos are visible in dnf repolist"
                ))
                total_points += 3
            elif baseos_visible or appstream_visible:
                checks.append(ValidationCheck(
                    name="repos_visible",
                    passed=False,
                    points=1,
                    max_points=3,
                    message="Only one of the two repos is visible in dnf repolist"
                ))
                total_points += 1
            else:
                checks.append(ValidationCheck(
                    name="repos_visible",
                    passed=False,
                    points=0,
                    max_points=3,
                    message="Neither repo is visible in dnf repolist"
                ))
        else:
            checks.append(ValidationCheck(
                name="repos_visible",
                passed=False,
                points=0,
                max_points=3,
                message="Could not run dnf repolist"
            ))

        passed = total_points >= (self.points * 0.7)
        return ValidationResult(self.id, passed, total_points, self.points, checks)


@TaskRegistry.register("repos")
class TroubleshootBrokenRepoTask(BaseTask):
    """Troubleshoot and fix a misconfigured repository."""

    def __init__(self):
        super().__init__(
            id="repo_troubleshoot_001",
            category="repos",
            difficulty="hard",
            points=15
        )
        self.requires_persistence = False
        self.tags = []
        self.exam_tips = [
            "Common repo issues: wrong URL, missing gpgkey, typos in enabled/gpgcheck",
            "Use 'dnf repolist -v' for verbose repo info",
            "Use 'dnf clean all' after fixing repo files",
            "Check /var/log/dnf.log for error details",
        ]
        self.repo_id = None
        self.repo_file = None
        self.break_type = None
        self.correct_url = None
        self.broken_url = None

    def generate(self, **params):
        """Generate a troubleshooting task for a broken repository."""
        # Real, reachable correct URLs so a fixed repo actually resolves (and an
        # enabled broken one doesn't poison dnf for other tasks).
        break_scenarios = [
            {
                'repo_id': 'broken-baseos',
                'break_type': 'wrong_url',
                'correct_url': 'https://dl.rockylinux.org/pub/rocky/10/BaseOS/x86_64/os/',
                'broken_url': 'https://dl.rockylinux.org/pub/rocky/9/BaseOS/x86_64/os/',
                'desc': 'The BaseOS URL points to the wrong major version (9 instead of 10)',
            },
            {
                'repo_id': 'broken-appstream',
                'break_type': 'missing_baseurl',
                'correct_url': 'https://repo.almalinux.org/almalinux/10/AppStream/x86_64/os/',
                'broken_url': '',
                'desc': 'The AppStream repository has no baseurl configured',
            },
            {
                'repo_id': 'broken-epel',
                'break_type': 'disabled',
                'correct_url': 'https://dl.fedoraproject.org/pub/epel/10/Everything/x86_64/',
                'broken_url': 'https://dl.fedoraproject.org/pub/epel/10/Everything/x86_64/',
                'desc': 'The EPEL repository exists but is disabled (enabled=0)',
            },
            {
                'repo_id': 'broken-extras',
                'break_type': 'bad_gpgkey',
                'correct_url': 'https://dl.rockylinux.org/pub/rocky/10/extras/x86_64/os/',
                'broken_url': 'https://dl.rockylinux.org/pub/rocky/10/extras/x86_64/os/',
                'desc': 'The extras repository has an invalid GPG key path',
            },
            {
                'repo_id': 'broken-crb',
                'break_type': 'typo_enabled',
                'correct_url': 'https://repo.almalinux.org/almalinux/10/CRB/x86_64/os/',
                'broken_url': 'https://repo.almalinux.org/almalinux/10/CRB/x86_64/os/',
                'desc': 'The CRB repository has a typo (enbled=1 instead of enabled=1)',
            },
        ]

        scenario = params.get('scenario', random.choice(break_scenarios))
        self.repo_id = scenario['repo_id']
        self.break_type = scenario['break_type']
        self.correct_url = scenario['correct_url']
        self.broken_url = scenario['broken_url']
        self.repo_file = f'/etc/yum.repos.d/{self.repo_id}.repo'

        self.description = (
            f"A repository is misconfigured and not working properly:\n"
            f"  - Repository file: {self.repo_file}\n"
            f"  - Problem: {scenario['desc']}\n"
            f"  - Expected base URL: {self.correct_url}\n"
            f"  - Fix the repository so that:\n"
            f"    * The repo ID is {self.repo_id}\n"
            f"    * The baseurl is {self.correct_url}\n"
            f"    * The repository is enabled\n"
            f"    * Run 'dnf clean all' after fixing"
        )

        self.hints = [
            f"Check the repo file: cat {self.repo_file}",
            f"Look for errors in the file format",
            f"Ensure baseurl={self.correct_url}",
            "Ensure enabled=1 (check for typos)",
            "After fixing: dnf clean all && dnf repolist",
        ]

        return self

    def validate(self):
        """Validate that the broken repository has been fixed."""
        checks = []
        total_points = 0

        # Check 1: Repo file exists (2 points)
        result = execute_safe(['test', '-f', self.repo_file])
        if not result.success:
            checks.append(ValidationCheck(
                name="repo_file_exists",
                passed=False,
                points=0,
                max_points=2,
                message=f"Repository file {self.repo_file} not found"
            ))
            return ValidationResult(self.id, False, 0, self.points, checks)

        checks.append(ValidationCheck(
            name="repo_file_exists",
            passed=True,
            points=2,
            message=f"Repository file {self.repo_file} exists"
        ))
        total_points += 2

        # Check 2: Correct repo section (2 points)
        result = execute_safe(['grep', '-c', f'\\[{self.repo_id}\\]', self.repo_file])
        if result.success and result.stdout.strip() != '0':
            checks.append(ValidationCheck(
                name="repo_section",
                passed=True,
                points=2,
                message=f"Repository section [{self.repo_id}] found"
            ))
            total_points += 2
        else:
            checks.append(ValidationCheck(
                name="repo_section",
                passed=False,
                points=0,
                max_points=2,
                message=f"Repository section [{self.repo_id}] not found"
            ))

        # Check 3: Correct baseurl (4 points)
        result = execute_safe(['grep', '-c', f'baseurl={self.correct_url}', self.repo_file])
        if result.success and result.stdout.strip() != '0':
            checks.append(ValidationCheck(
                name="baseurl_fixed",
                passed=True,
                points=4,
                message="Base URL has been corrected"
            ))
            total_points += 4
        else:
            checks.append(ValidationCheck(
                name="baseurl_fixed",
                passed=False,
                points=0,
                max_points=4,
                message=f"baseurl={self.correct_url} not found in repo file"
            ))

        # Check 4: Repository is enabled (3 points)
        result = execute_safe(['grep', '-c', 'enabled=1', self.repo_file])
        if result.success and result.stdout.strip() != '0':
            checks.append(ValidationCheck(
                name="repo_enabled",
                passed=True,
                points=3,
                message="Repository is enabled (enabled=1)"
            ))
            total_points += 3
        else:
            checks.append(ValidationCheck(
                name="repo_enabled",
                passed=False,
                points=0,
                max_points=3,
                message="Repository is not enabled (enabled=1 not found)"
            ))

        # Check 5: Repo visible in dnf repolist (4 points)
        result = execute_safe(['dnf', 'repolist'])
        if result.success and self.repo_id in result.stdout:
            checks.append(ValidationCheck(
                name="repo_visible",
                passed=True,
                points=4,
                message=f"Repository {self.repo_id} is visible in dnf repolist"
            ))
            total_points += 4
        else:
            checks.append(ValidationCheck(
                name="repo_visible",
                passed=False,
                points=0,
                max_points=4,
                message=f"Repository {self.repo_id} is not visible in dnf repolist"
            ))

        passed = total_points >= (self.points * 0.7)
        return ValidationResult(self.id, passed, total_points, self.points, checks)


@TaskRegistry.register("repos")
class AddThirdPartyRepoTask(BaseTask):
    """Add a third-party repository with full configuration."""

    def __init__(self):
        super().__init__(
            id="repo_thirdparty_001",
            category="repos",
            difficulty="medium",
            points=10
        )
        self.requires_persistence = True
        self.tags = []
        self.exam_tips = [
            "Third-party repos often require importing a GPG key",
            "Use dnf config-manager --add-repo for quick setup",
            "Always verify with dnf repolist after adding",
            "Some repos may also require enabling CRB/PowerTools"
        ]
        self.repo_id = None
        self.repo_name = None
        self.base_url = None
        self.gpgcheck = None
        self.gpg_key_url = None

    def generate(self, **params):
        """Generate a third-party repository addition task using a real,
        reachable third-party repo (with a real GPG key) from REAL_REPOS."""
        # Third-party = not the distro core rebuilds (Rocky/Alma BaseOS etc.).
        third_party = [r for r in REAL_REPOS_WITH_GPG
                       if not r['repo_id'].startswith(('rocky10', 'alma10'))]

        config = params.get('config', random.choice(third_party))
        self.repo_id = config['repo_id']
        self.repo_name = config['repo_name']
        self.base_url = config['base_url']
        self.gpgcheck = config.get('gpgcheck', 1)
        self.gpg_key_url = config['gpg_key_url']

        gpg_info = ""
        if self.gpgcheck:
            gpg_info = (
                f"  - GPG check: enabled\n"
                f"  - GPG key: {self.gpg_key_url}\n"
            )
        else:
            gpg_info = "  - GPG check: disabled\n"

        self.description = (
            f"Add a third-party package repository:\n"
            f"  - Repository ID: {self.repo_id}\n"
            f"  - Repository name: {self.repo_name}\n"
            f"  - Base URL: {self.base_url}\n"
            f"{gpg_info}"
            f"  - The repository must be enabled\n"
            f"  - Create file: /etc/yum.repos.d/{self.repo_id}.repo"
        )

        self.hints = [
            f"Create /etc/yum.repos.d/{self.repo_id}.repo",
            f"Format:\n[{self.repo_id}]\nname={self.repo_name}\n"
            f"baseurl={self.base_url}\nenabled=1\n"
            f"gpgcheck={self.gpgcheck}\ngpgkey={self.gpg_key_url}",
            f"Or quick add: dnf config-manager --add-repo {self.base_url}",
            "Verify: dnf repolist",
        ]

        return self

    def validate(self):
        """Validate third-party repository configuration."""
        checks = []
        total_points = 0
        repo_file = f'/etc/yum.repos.d/{self.repo_id}.repo'

        # Check 1: Repo file exists (2 points)
        # Also check for auto-generated filename from dnf config-manager
        result = execute_safe(['test', '-f', repo_file])
        file_found = result.success
        actual_file = repo_file

        if not file_found:
            # dnf config-manager creates files named after the URL
            result2 = execute_safe(['grep', '-rl', self.base_url, '/etc/yum.repos.d/'])
            if result2.success and result2.stdout.strip():
                file_found = True
                actual_file = result2.stdout.strip().splitlines()[0]

        if file_found:
            checks.append(ValidationCheck(
                name="repo_file_exists",
                passed=True,
                points=2,
                message=f"Repository file found: {actual_file}"
            ))
            total_points += 2
        else:
            checks.append(ValidationCheck(
                name="repo_file_exists",
                passed=False,
                points=0,
                max_points=2,
                message=f"No repo file found for {self.repo_id}"
            ))
            return ValidationResult(self.id, False, 0, self.points, checks)

        # Check 2: baseurl configured (3 points)
        result = execute_safe(['grep', '-c', f'baseurl={self.base_url}', actual_file])
        if result.success and result.stdout.strip() != '0':
            checks.append(ValidationCheck(
                name="baseurl_correct",
                passed=True,
                points=3,
                message="Base URL correctly configured"
            ))
            total_points += 3
        else:
            result2 = execute_safe(['grep', '-c', 'baseurl=', actual_file])
            if result2.success and result2.stdout.strip() != '0':
                checks.append(ValidationCheck(
                    name="baseurl_correct",
                    passed=False,
                    points=1,
                    max_points=3,
                    message="baseurl present but does not match expected URL"
                ))
                total_points += 1
            else:
                checks.append(ValidationCheck(
                    name="baseurl_correct",
                    passed=False,
                    points=0,
                    max_points=3,
                    message="baseurl not found in repo file"
                ))

        # Check 3: enabled=1 (2 points)
        result = execute_safe(['grep', '-c', 'enabled=1', actual_file])
        if result.success and result.stdout.strip() != '0':
            checks.append(ValidationCheck(
                name="repo_enabled",
                passed=True,
                points=2,
                message="Repository is enabled"
            ))
            total_points += 2
        else:
            checks.append(ValidationCheck(
                name="repo_enabled",
                passed=False,
                points=0,
                max_points=2,
                message="Repository is not enabled (enabled=1 not found)"
            ))

        # Check 4: gpgcheck and gpgkey (3 points)
        if self.gpgcheck:
            result = execute_safe(['grep', '-c', 'gpgcheck=1', actual_file])
            gpg_ok = result.success and result.stdout.strip() != '0'
            result2 = execute_safe(['grep', '-c', 'gpgkey=', actual_file])
            key_ok = result2.success and result2.stdout.strip() != '0'

            if gpg_ok and key_ok:
                checks.append(ValidationCheck(
                    name="gpg_configured",
                    passed=True,
                    points=3,
                    message="GPG check enabled and key configured"
                ))
                total_points += 3
            elif gpg_ok:
                checks.append(ValidationCheck(
                    name="gpg_configured",
                    passed=False,
                    points=1,
                    max_points=3,
                    message="gpgcheck=1 set but gpgkey not configured"
                ))
                total_points += 1
            else:
                checks.append(ValidationCheck(
                    name="gpg_configured",
                    passed=False,
                    points=0,
                    max_points=3,
                    message="GPG checking not properly configured"
                ))
        else:
            result = execute_safe(['grep', '-c', 'gpgcheck=0', actual_file])
            if result.success and result.stdout.strip() != '0':
                checks.append(ValidationCheck(
                    name="gpg_configured",
                    passed=True,
                    points=3,
                    message="GPG check correctly disabled"
                ))
                total_points += 3
            else:
                checks.append(ValidationCheck(
                    name="gpg_configured",
                    passed=False,
                    points=0,
                    max_points=3,
                    message="gpgcheck setting not correct"
                ))

        passed = total_points >= (self.points * 0.7)
        return ValidationResult(self.id, passed, total_points, self.points, checks)
