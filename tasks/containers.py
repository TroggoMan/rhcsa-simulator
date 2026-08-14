"""
Container management tasks — EX200 v9 only.

"Manage containers" is its own objective section on the RHEL 9 exam and was
dropped entirely from RHEL 10, so every task here is filtered out when the
simulator runs in v10 mode (settings.VERSION_EXCLUDED_CATEGORIES).

Objectives covered:
  - Find and retrieve container images from a remote registry
  - Inspect container images
  - Perform container management using commands such as podman and skopeo
  - Perform basic container management (run, start, stop, list)
  - Run a service inside a container
  - Configure a container to start automatically as a systemd service
  - Attach persistent storage to a container

TWO THINGS MAKE THIS CATEGORY DIFFERENT
---------------------------------------
1. It needs an image. Everything else in this simulator works offline, but
   you cannot practise containers without one. Rather than fail with a
   confusing "no such image", tasks check what is present up front:
   image_available() picks an image the box already has, and when nothing is
   cached the task says so in its own description and the affected checks are
   skipped rather than failed. A candidate who did the work correctly must
   never lose points because the lab had no registry access.

2. Rootless is the exam-realistic default. Containers on the exam are run as
   an ordinary user, which changes where the systemd unit lives
   (~/.config/systemd/user), requires lingering for boot start, and needs :Z
   on bind mounts under SELinux. Tasks say which user to work as, and
   validation looks in that user's context.

All validation is read-only: podman/skopeo are restricted to inspection
subcommands by validators/safe_executor.py, so a check can never destroy the
container it is grading.
"""

import logging
import random

from tasks.base import BaseTask
from tasks.registry import TaskRegistry
from core.validator import ValidationCheck, ValidationResult
from validators.safe_executor import execute_safe

logger = logging.getLogger(__name__)


# Images small enough to be reasonable on a lab box, most-preferred first.
# ubi-minimal is ~40MB and ships everything these tasks need.
CANDIDATE_IMAGES = [
    'registry.access.redhat.com/ubi9/ubi-minimal',
    'registry.access.redhat.com/ubi9/ubi',
    'registry.access.redhat.com/ubi8/ubi-minimal',
    'quay.io/podman/hello',
    'docker.io/library/alpine',
]

# A registry the exam-style "pull an image" task can name. The real exam
# provides the registry in the question, so we do too.
DEFAULT_REGISTRY = 'registry.access.redhat.com'


def podman_available():
    """True if podman is installed and usable."""
    result = execute_safe(['podman', 'version', '--format', '{{.Client.Version}}'])
    return bool(result.success and result.stdout.strip())


def local_images():
    """Image references already present on the box (no network needed)."""
    result = execute_safe(['podman', 'images', '--format', '{{.Repository}}:{{.Tag}}'])
    if not result.success:
        return []
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]


def image_available():
    """An image the candidate can actually use, or None if the box has none.

    Prefers our candidate list, then falls back to whatever is cached — a box
    that pulled something else is still a box you can practise on.
    """
    have = local_images()
    if not have:
        return None
    for wanted in CANDIDATE_IMAGES:
        for ref in have:
            if ref.split(':')[0] == wanted:
                return ref
    for ref in have:
        if '<none>' not in ref:
            return ref
    return None


def _exam_user():
    """A non-root user to run rootless containers as.

    Container tasks are the one place the exam explicitly expects rootless
    operation, so the task creates its own user rather than borrowing one the
    candidate may also be graded on elsewhere.
    """
    return 'container'


def _user_exists(username):
    return execute_safe(['id', username]).success


class _ContainerTask(BaseTask):
    """Shared setup for container tasks: podman/image availability, and the
    skip-vs-fail decision that follows from it."""

    exam_versions = (9,)          # dropped from EX200 v10
    required_packages = ['podman']

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.image = None
        self.tags = ['v9-only', 'containers']

    def _probe_environment(self):
        """Cache what the lab can actually do. Never raises."""
        try:
            self.has_podman = podman_available()
            self.image = image_available() if self.has_podman else None
        except Exception as e:                      # pragma: no cover
            logger.debug("container probe failed: %s", e)
            self.has_podman = False
            self.image = None

    def _lab_note(self):
        """Text appended to a description when the lab is short of something,
        so the candidate knows before spending exam time on it."""
        if not getattr(self, 'has_podman', False):
            return ("\n\nNOTE: podman is not installed on this system, so this "
                    "task cannot be completed here. Install it with "
                    "'dnf install -y podman' and regenerate the task.")
        if not self.image:
            return ("\n\nNOTE: no container image is cached locally and this "
                    "lab may have no registry access. Checks that need a "
                    "running container will be SKIPPED rather than failed.")
        return ""

    def _skip_or_fail(self, checks, name, points, message):
        """Record a check the lab could not observe.

        Skips are excluded from the score denominator, so a candidate is never
        penalised for a limitation of the box.
        """
        if not self.image or not getattr(self, 'has_podman', False):
            checks.append(ValidationCheck(
                name=name, passed=True, points=0, max_points=0,
                message=f"SKIPPED (no usable container image): {message}"))
            return True
        return False


@TaskRegistry.register("containers")
class PullContainerImageTask(_ContainerTask):
    """Find and retrieve a container image from a remote registry."""

    def __init__(self):
        super().__init__(id="containers_pull_001", category="containers",
                         difficulty="easy", points=8)
        self.requires_persistence = False
        self.exam_tips = [
            "podman search registry.access.redhat.com/ubi finds images",
            "podman pull <registry>/<namespace>/<image>:<tag>",
            "podman images lists what is already local — check before pulling",
            "skopeo inspect docker://<image> reads a remote image without pulling it",
        ]

    def generate(self, **params):
        self._probe_environment()
        self.image_name = params.get('image_name', 'ubi9/ubi-minimal')
        self.description = (
            f"Retrieve a container image from a remote registry:\n"
            f"  - Registry: {DEFAULT_REGISTRY}\n"
            f"  - Image: {self.image_name}\n"
            f"  - Pull the image so it is available locally\n"
            f"  - Verify it appears in the local image list"
        ) + self._lab_note()
        self.hints = [
            f"podman pull {DEFAULT_REGISTRY}/{self.image_name}",
            "podman images  — confirm it is listed",
            "podman search can find images if you do not know the exact name",
        ]
        return self

    def validate(self):
        checks = []
        total = 0

        if not podman_available():
            checks.append(ValidationCheck(
                name="podman_installed", passed=False, points=0, max_points=8,
                message="podman is not installed"))
            return ValidationResult(self.id, False, 0, self.points, checks)

        images = local_images()
        wanted = self.image_name.split(':')[0]
        matched = [ref for ref in images if wanted in ref]

        if matched:
            checks.append(ValidationCheck(
                name="image_present", passed=True, points=8,
                message=f"Image present locally: {matched[0]}"))
            total += 8
        elif images:
            # They pulled something, just not the named image. Partial credit
            # is wrong here — the objective is retrieving a *specific* image.
            checks.append(ValidationCheck(
                name="image_present", passed=False, points=0, max_points=8,
                message=(f"'{self.image_name}' not found locally. Images "
                         f"present: {', '.join(images[:3])}")))
        else:
            checks.append(ValidationCheck(
                name="image_present", passed=False, points=0, max_points=8,
                message="No container images are present locally"))

        return ValidationResult(self.id, total >= 8, total, self.points, checks)


@TaskRegistry.register("containers")
class InspectContainerImageTask(_ContainerTask):
    """Inspect a container image and record a specific field."""

    def __init__(self):
        super().__init__(id="containers_inspect_002", category="containers",
                         difficulty="medium", points=10)
        self.requires_persistence = True
        self.exam_tips = [
            "podman inspect <image> returns JSON — use --format to pull one field",
            "podman image inspect --format '{{.Config.Cmd}}' <image>",
            "skopeo inspect docker://<image> works without pulling the image",
        ]

    def generate(self, **params):
        self._probe_environment()
        self.report_path = params.get('report_path', '/root/image-report.txt')
        self.description = (
            f"Inspect a container image and record what you find:\n"
            f"  - Inspect a container image available on this system\n"
            f"  - Write the image's Id (or Digest) to {self.report_path}\n"
            f"  - The file must contain only that value"
        ) + self._lab_note()
        self.hints = [
            "podman images  — pick an image that exists locally",
            "podman inspect --format '{{.Id}}' <image>",
            f"podman inspect --format '{{{{.Id}}}}' <image> > {self.report_path}",
        ]
        return self

    def validate(self):
        checks = []
        total = 0
        self._probe_environment()

        result = execute_safe(['test', '-f', self.report_path])
        if not result.success:
            checks.append(ValidationCheck(
                name="report_exists", passed=False, points=0, max_points=4,
                message=f"{self.report_path} does not exist"))
        else:
            checks.append(ValidationCheck(
                name="report_exists", passed=True, points=4,
                message=f"{self.report_path} exists"))
            total += 4

        if self._skip_or_fail(checks, "report_matches_image", 6,
                              "cannot confirm the recorded id matches an image"):
            passed = total >= 4
            return ValidationResult(self.id, passed, total, self.points, checks)

        content = execute_safe(['cat', self.report_path])
        recorded = (content.stdout or '').strip() if content.success else ''
        ids = execute_safe(['podman', 'images', '--format', '{{.ID}}'])
        digests = execute_safe(['podman', 'images', '--format', '{{.Digest}}'])
        known = set()
        for r in (ids, digests):
            if r.success:
                known.update(x.strip() for x in r.stdout.splitlines() if x.strip())

        # podman abbreviates IDs in some output forms, so match on prefix.
        hit = recorded and any(
            k.startswith(recorded) or recorded.startswith(k) or recorded in k
            for k in known)
        if hit:
            checks.append(ValidationCheck(
                name="report_matches_image", passed=True, points=6,
                message="Recorded value matches a local image"))
            total += 6
        else:
            checks.append(ValidationCheck(
                name="report_matches_image", passed=False, points=0, max_points=6,
                message=("Recorded value does not match any local image id "
                         "or digest")))

        return ValidationResult(self.id, total >= 7, total, self.points, checks)


@TaskRegistry.register("containers")
class RunNamedContainerTask(_ContainerTask):
    """Basic container management: run a named container and keep it running."""

    def __init__(self):
        super().__init__(id="containers_run_003", category="containers",
                         difficulty="medium", points=12)
        self.requires_persistence = False
        self.exam_tips = [
            "podman run -d --name <name> <image> keeps it in the background",
            "A container exits immediately unless its command keeps running",
            "podman ps shows running; podman ps -a shows stopped too",
        ]

    def generate(self, **params):
        self._probe_environment()
        self.container_name = params.get('container_name',
                                         random.choice(['webapp', 'appsrv',
                                                        'testsrv', 'mysvc']))
        self.description = (
            f"Run a container and leave it running:\n"
            f"  - Name: {self.container_name}\n"
            f"  - Use a container image available on this system\n"
            f"  - The container must be running (not exited) when checked\n"
            f"  - Run it detached"
        ) + self._lab_note()
        self.hints = [
            f"podman run -d --name {self.container_name} <image> sleep infinity",
            "podman ps  — confirm STATUS shows Up",
            "A plain 'podman run <image>' exits as soon as its command finishes",
        ]
        return self

    def validate(self):
        checks = []
        total = 0
        self._probe_environment()

        if self._skip_or_fail(checks, "container_running", 12,
                              f"cannot check for container '{self.container_name}'"):
            return ValidationResult(self.id, True, 0, 0, checks)

        result = execute_safe(['podman', 'ps', '-a', '--format',
                               '{{.Names}}|{{.State}}|{{.Image}}'])
        found = None
        for line in (result.stdout or '').splitlines():
            parts = line.split('|')
            if parts and parts[0].strip() == self.container_name:
                found = parts
                break

        if not found:
            checks.append(ValidationCheck(
                name="container_exists", passed=False, points=0, max_points=6,
                message=f"No container named '{self.container_name}'"))
            checks.append(ValidationCheck(
                name="container_running", passed=False, points=0, max_points=6,
                message="Container does not exist, so it is not running"))
            return ValidationResult(self.id, False, 0, self.points, checks)

        checks.append(ValidationCheck(
            name="container_exists", passed=True, points=6,
            message=f"Container '{self.container_name}' exists "
                    f"(image {found[2].strip() if len(found) > 2 else '?'})"))
        total += 6

        state = found[1].strip().lower() if len(found) > 1 else ''
        if state == 'running':
            checks.append(ValidationCheck(
                name="container_running", passed=True, points=6,
                message="Container is running"))
            total += 6
        else:
            checks.append(ValidationCheck(
                name="container_running", passed=False, points=0, max_points=6,
                message=(f"Container state is '{state}', not running. A "
                         f"container exits when its command finishes — give "
                         f"it a long-running one.")))

        return ValidationResult(self.id, total >= 12, total, self.points, checks)


@TaskRegistry.register("containers")
class ContainerPersistentStorageTask(_ContainerTask):
    """Attach persistent storage to a container."""

    def __init__(self):
        super().__init__(id="containers_storage_004", category="containers",
                         difficulty="exam", points=15)
        self.requires_persistence = True
        self.exam_tips = [
            "podman run -v /host/path:/container/path:Z ...",
            "The :Z suffix relabels the host directory for SELinux — without "
            "it the container gets permission denied on an enforcing system",
            "podman inspect --format '{{.Mounts}}' <container> shows the mount",
            "A named volume (podman volume create) also satisfies persistence",
        ]

    def generate(self, **params):
        self._probe_environment()
        self.container_name = params.get('container_name', 'datasvc')
        self.host_dir = params.get('host_dir', '/opt/container-data')
        self.mount_point = params.get('mount_point', '/data')
        self.description = (
            f"Attach persistent storage to a container:\n"
            f"  - Host directory: {self.host_dir}\n"
            f"  - Mounted inside the container at: {self.mount_point}\n"
            f"  - Container name: {self.container_name}\n"
            f"  - Data written in the container must survive the container "
            f"being removed and recreated\n"
            f"  - SELinux must remain enforcing"
        ) + self._lab_note()
        self.hints = [
            f"mkdir -p {self.host_dir}",
            f"podman run -d --name {self.container_name} "
            f"-v {self.host_dir}:{self.mount_point}:Z <image> sleep infinity",
            "The :Z relabels the host dir — check with ls -Zd",
            "Verify: podman inspect --format '{{.Mounts}}' <container>",
        ]
        return self

    def validate(self):
        checks = []
        total = 0
        self._probe_environment()

        # Host directory — checkable regardless of container state.
        if execute_safe(['test', '-d', self.host_dir]).success:
            checks.append(ValidationCheck(
                name="host_dir", passed=True, points=5,
                message=f"{self.host_dir} exists"))
            total += 5
        else:
            checks.append(ValidationCheck(
                name="host_dir", passed=False, points=0, max_points=5,
                message=f"{self.host_dir} does not exist"))

        if self._skip_or_fail(checks, "volume_mounted", 10,
                              "cannot inspect the container's mounts"):
            return ValidationResult(self.id, total >= 5, total, 5, checks)

        result = execute_safe(['podman', 'inspect', '--format',
                               '{{range .Mounts}}{{.Source}}:{{.Destination}} {{end}}',
                               self.container_name])
        mounts = (result.stdout or '').strip() if result.success else ''
        expected = f"{self.host_dir}:{self.mount_point}"

        if expected in mounts:
            checks.append(ValidationCheck(
                name="volume_mounted", passed=True, points=7,
                message=f"{self.host_dir} is mounted at {self.mount_point}"))
            total += 7
        elif mounts:
            checks.append(ValidationCheck(
                name="volume_mounted", passed=False, points=0, max_points=7,
                message=f"Expected {expected}, container has: {mounts}"))
        else:
            checks.append(ValidationCheck(
                name="volume_mounted", passed=False, points=0, max_points=7,
                message=(f"Container '{self.container_name}' has no mounts "
                         f"(or does not exist)")))

        # SELinux label — the part candidates most often miss.
        ctx = execute_safe(['ls', '-Zd', self.host_dir])
        if ctx.success and 'container_file_t' in (ctx.stdout or ''):
            checks.append(ValidationCheck(
                name="selinux_label", passed=True, points=3,
                message="Host directory carries container_file_t (:Z was used)"))
            total += 3
        elif execute_safe(['getenforce']).stdout.strip().lower() != 'enforcing':
            checks.append(ValidationCheck(
                name="selinux_label", passed=True, points=0, max_points=0,
                message="SKIPPED (SELinux not enforcing): container_file_t label"))
        else:
            checks.append(ValidationCheck(
                name="selinux_label", passed=False, points=0, max_points=3,
                message=("Host directory is not labelled container_file_t — "
                         "mount with :Z so the container can access it")))

        return ValidationResult(self.id, total >= 11, total, self.points, checks)


@TaskRegistry.register("containers")
class ContainerSystemdServiceTask(_ContainerTask):
    """Configure a container to start automatically as a systemd service."""

    def __init__(self):
        super().__init__(id="containers_systemd_005", category="containers",
                         difficulty="exam", points=18)
        self.requires_persistence = True
        self.exam_tips = [
            "Rootless: units live in ~/.config/systemd/user/",
            "podman generate systemd --name <c> --files --new  (RHEL 9)",
            "Quadlet (.container files) is the newer way and also acceptable",
            "systemctl --user enable --now <unit>",
            "loginctl enable-linger <user> — without it the user's services "
            "stop at logout and never start at boot",
            "Reload after writing a unit: systemctl --user daemon-reload",
        ]

    def generate(self, **params):
        self._probe_environment()
        self.username = params.get('username', _exam_user())
        self.container_name = params.get('container_name', 'websvc')
        self.unit_name = f"container-{self.container_name}.service"
        self.description = (
            f"Configure a container to start automatically at boot:\n"
            f"  - Run as the user '{self.username}' (rootless), not root\n"
            f"  - Container name: {self.container_name}\n"
            f"  - Create a systemd user service that starts it\n"
            f"  - The service must be enabled so it starts at boot, without "
            f"that user having to log in\n"
            f"  - Create the user if it does not exist"
        ) + self._lab_note()
        self.hints = [
            f"useradd {self.username}",
            f"loginctl enable-linger {self.username}",
            f"su - {self.username}",
            f"podman run -d --name {self.container_name} <image> sleep infinity",
            f"mkdir -p ~/.config/systemd/user && cd ~/.config/systemd/user",
            f"podman generate systemd --name {self.container_name} --files --new",
            f"systemctl --user daemon-reload && systemctl --user enable --now "
            f"{self.unit_name}",
        ]
        return self

    def validate(self):
        checks = []
        total = 0
        self._probe_environment()

        # 1. User exists (5)
        if _user_exists(self.username):
            checks.append(ValidationCheck(
                name="user_exists", passed=True, points=5,
                message=f"User '{self.username}' exists"))
            total += 5
        else:
            checks.append(ValidationCheck(
                name="user_exists", passed=False, points=0, max_points=5,
                message=f"User '{self.username}' does not exist"))
            # Everything else is scoped to that user, so stop here.
            checks.append(ValidationCheck(
                name="linger_enabled", passed=False, points=0, max_points=5,
                message="Cannot check lingering without the user"))
            checks.append(ValidationCheck(
                name="unit_enabled", passed=False, points=0, max_points=8,
                message="Cannot check the user service without the user"))
            return ValidationResult(self.id, False, total, self.points, checks)

        # 2. Lingering (5) — the bit that makes "at boot" actually true.
        linger = execute_safe(['ls', f'/var/lib/systemd/linger/{self.username}'])
        if linger.success:
            checks.append(ValidationCheck(
                name="linger_enabled", passed=True, points=5,
                message=f"Lingering is enabled for '{self.username}'"))
            total += 5
        else:
            checks.append(ValidationCheck(
                name="linger_enabled", passed=False, points=0, max_points=5,
                message=(f"Lingering is not enabled — the container will not "
                         f"start until '{self.username}' logs in. "
                         f"loginctl enable-linger {self.username}")))

        # 3. An enabled user unit referencing the container (8).
        home = f"/home/{self.username}"
        unit_dir = f"{home}/.config/systemd/user"
        listing = execute_safe(['ls', unit_dir])
        unit_files = [f.strip() for f in (listing.stdout or '').splitlines()
                      if f.strip().endswith(('.service', '.container'))]

        if not unit_files:
            checks.append(ValidationCheck(
                name="unit_enabled", passed=False, points=0, max_points=8,
                message=f"No systemd user unit found in {unit_dir}"))
            return ValidationResult(self.id, False, total, self.points, checks)

        # Does any of them mention the container?
        referencing = []
        for unit in unit_files:
            body = execute_safe(['cat', f'{unit_dir}/{unit}'])
            if body.success and self.container_name in (body.stdout or ''):
                referencing.append(unit)

        wants = execute_safe(['ls', f'{unit_dir}/default.target.wants'])
        enabled_names = [f.strip() for f in (wants.stdout or '').splitlines()
                         if f.strip()]

        if referencing and any(u in enabled_names for u in referencing):
            checks.append(ValidationCheck(
                name="unit_enabled", passed=True, points=8,
                message=f"User unit {referencing[0]} is enabled for boot"))
            total += 8
        elif referencing:
            checks.append(ValidationCheck(
                name="unit_enabled", passed=False, points=0, max_points=8,
                message=(f"Unit {referencing[0]} exists but is not enabled — "
                         f"systemctl --user enable {referencing[0]}")))
        else:
            checks.append(ValidationCheck(
                name="unit_enabled", passed=False, points=0, max_points=8,
                message=(f"Found unit(s) {', '.join(unit_files)} but none "
                         f"reference container '{self.container_name}'")))

        return ValidationResult(self.id, total >= 13, total, self.points, checks)


@TaskRegistry.register("containers")
class ContainerServicePortTask(_ContainerTask):
    """Run a service inside a container and publish it on a host port."""

    def __init__(self):
        super().__init__(id="containers_service_006", category="containers",
                         difficulty="exam", points=15)
        self.requires_persistence = False
        self.exam_tips = [
            "podman run -d -p <host>:<container> ... publishes a port",
            "Rootless containers cannot bind host ports below 1024",
            "podman port <container> shows the published mapping",
            "ss -tlnp confirms something is actually listening on the host",
        ]

    def generate(self, **params):
        self._probe_environment()
        self.container_name = params.get('container_name', 'httpsvc')
        self.host_port = params.get('host_port', random.choice([8080, 8088, 8090]))
        self.container_port = params.get('container_port', 80)
        self.description = (
            f"Run a service inside a container and publish it:\n"
            f"  - Container name: {self.container_name}\n"
            f"  - The service inside the container listens on port "
            f"{self.container_port}\n"
            f"  - Publish it on host port {self.host_port}\n"
            f"  - The container must be running when checked"
        ) + self._lab_note()
        self.hints = [
            f"podman run -d --name {self.container_name} "
            f"-p {self.host_port}:{self.container_port} <image>",
            f"podman port {self.container_name}",
            f"ss -tlnp | grep {self.host_port}",
            "Rootless containers cannot publish ports below 1024",
        ]
        return self

    def validate(self):
        checks = []
        total = 0
        self._probe_environment()

        if self._skip_or_fail(checks, "port_published", 15,
                              f"cannot check container '{self.container_name}'"):
            return ValidationResult(self.id, True, 0, 0, checks)

        result = execute_safe(['podman', 'ps', '--format',
                               '{{.Names}}|{{.Ports}}'])
        line = None
        for row in (result.stdout or '').splitlines():
            if row.split('|')[0].strip() == self.container_name:
                line = row
                break

        if not line:
            checks.append(ValidationCheck(
                name="container_running", passed=False, points=0, max_points=7,
                message=f"No running container named '{self.container_name}'"))
            checks.append(ValidationCheck(
                name="port_published", passed=False, points=0, max_points=8,
                message="Container is not running, so no port is published"))
            return ValidationResult(self.id, False, 0, self.points, checks)

        checks.append(ValidationCheck(
            name="container_running", passed=True, points=7,
            message=f"Container '{self.container_name}' is running"))
        total += 7

        ports = line.split('|', 1)[1] if '|' in line else ''
        if f":{self.host_port}" in ports and str(self.container_port) in ports:
            checks.append(ValidationCheck(
                name="port_published", passed=True, points=8,
                message=f"Port {self.host_port} -> {self.container_port} published"))
            total += 8
        else:
            checks.append(ValidationCheck(
                name="port_published", passed=False, points=0, max_points=8,
                message=(f"Expected {self.host_port}->{self.container_port}, "
                         f"container publishes: {ports.strip() or 'nothing'}")))

        return ValidationResult(self.id, total >= 15, total, self.points, checks)


@TaskRegistry.register("containers")
class SkopeoInspectRemoteTask(_ContainerTask):
    """Use skopeo to inspect a remote image without pulling it."""

    def __init__(self):
        super().__init__(id="containers_skopeo_007", category="containers",
                         difficulty="medium", points=10)
        self.requires_persistence = True
        self.required_packages = ['podman', 'skopeo']
        self.exam_tips = [
            "skopeo inspect docker://<registry>/<image> reads remote metadata",
            "No pull required, so it is fast and uses little disk",
            "skopeo list-tags docker://<image> enumerates available tags",
            "podman and skopeo are both named in the objective — know both",
        ]

    def generate(self, **params):
        self._probe_environment()
        self.report_path = params.get('report_path', '/root/skopeo-tags.txt')
        self.image_ref = params.get('image_ref',
                                    f'{DEFAULT_REGISTRY}/ubi9/ubi-minimal')
        self.description = (
            f"Inspect a container image without downloading it:\n"
            f"  - Image: {self.image_ref}\n"
            f"  - Use skopeo (not podman pull)\n"
            f"  - Save the inspection output to {self.report_path}"
        ) + self._lab_note()
        self.hints = [
            f"skopeo inspect docker://{self.image_ref}",
            f"skopeo inspect docker://{self.image_ref} > {self.report_path}",
            "skopeo needs the docker:// transport prefix",
        ]
        return self

    def validate(self):
        checks = []
        total = 0

        if not execute_safe(['test', '-f', self.report_path]).success:
            checks.append(ValidationCheck(
                name="report_exists", passed=False, points=0, max_points=10,
                message=f"{self.report_path} does not exist"))
            return ValidationResult(self.id, False, 0, self.points, checks)

        checks.append(ValidationCheck(
            name="report_exists", passed=True, points=4,
            message=f"{self.report_path} exists"))
        total += 4

        body = execute_safe(['cat', self.report_path])
        content = (body.stdout or '') if body.success else ''
        # skopeo inspect emits JSON with these keys; grading the shape rather
        # than exact bytes keeps it valid across skopeo versions.
        markers = ['Digest', 'RepoTags', 'Architecture', 'Layers']
        hits = [m for m in markers if m in content]

        if len(hits) >= 2:
            checks.append(ValidationCheck(
                name="report_is_inspection", passed=True, points=6,
                message=f"File contains skopeo inspection output ({', '.join(hits)})"))
            total += 6
        else:
            checks.append(ValidationCheck(
                name="report_is_inspection", passed=False, points=0, max_points=6,
                message=("File does not look like skopeo inspect output — "
                         "expected JSON with Digest/RepoTags/Architecture")))

        return ValidationResult(self.id, total >= 10, total, self.points, checks)


@TaskRegistry.register("containers")
class ContainerLifecycleTask(_ContainerTask):
    """Basic lifecycle: a container that exists but must be left stopped."""

    def __init__(self):
        super().__init__(id="containers_lifecycle_008", category="containers",
                         difficulty="easy", points=8)
        self.requires_persistence = False
        self.exam_tips = [
            "podman stop <name> leaves the container defined but not running",
            "podman ps -a shows stopped containers; podman ps alone does not",
            "'Exited' and 'Created' are different states — read the question",
        ]

    def generate(self, **params):
        self._probe_environment()
        self.container_name = params.get('container_name', 'idlesvc')
        self.description = (
            f"Manage a container's lifecycle:\n"
            f"  - Create a container named {self.container_name}\n"
            f"  - Start it, then stop it again\n"
            f"  - Leave it defined on the system but NOT running"
        ) + self._lab_note()
        self.hints = [
            f"podman run -d --name {self.container_name} <image> sleep infinity",
            f"podman stop {self.container_name}",
            f"podman ps -a  — it should be listed with a non-running state",
        ]
        return self

    def validate(self):
        checks = []
        total = 0
        self._probe_environment()

        if self._skip_or_fail(checks, "container_stopped", 8,
                              f"cannot check container '{self.container_name}'"):
            return ValidationResult(self.id, True, 0, 0, checks)

        result = execute_safe(['podman', 'ps', '-a', '--format',
                               '{{.Names}}|{{.State}}'])
        state = None
        for row in (result.stdout or '').splitlines():
            parts = row.split('|')
            if parts and parts[0].strip() == self.container_name:
                state = parts[1].strip().lower() if len(parts) > 1 else ''
                break

        if state is None:
            checks.append(ValidationCheck(
                name="container_exists", passed=False, points=0, max_points=4,
                message=f"No container named '{self.container_name}'"))
            checks.append(ValidationCheck(
                name="container_stopped", passed=False, points=0, max_points=4,
                message="Container does not exist"))
            return ValidationResult(self.id, False, 0, self.points, checks)

        checks.append(ValidationCheck(
            name="container_exists", passed=True, points=4,
            message=f"Container '{self.container_name}' is defined"))
        total += 4

        if state in ('exited', 'stopped', 'created', 'configured'):
            checks.append(ValidationCheck(
                name="container_stopped", passed=True, points=4,
                message=f"Container is not running (state: {state})"))
            total += 4
        else:
            checks.append(ValidationCheck(
                name="container_stopped", passed=False, points=0, max_points=4,
                message=f"Container is still running (state: {state})"))

        return ValidationResult(self.id, total >= 8, total, self.points, checks)
