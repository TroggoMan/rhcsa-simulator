"""
NFS server provisioning for NFS practice tasks.

The NFS tasks (tasks/network_storage.py) need a *real* NFS server to mount
from, otherwise the candidate can't actually complete or test them. This module
lets Setup provision one of two ways:

  * Local  — provision THIS machine as its own NFS server (loopback). No
    second box needed; candidates who only have one machine can still
    practice mount/fstab/autofs against a real, reachable export.
  * Remote — SSH into a RHEL box the user names and provision it the same
    way, over the network. Closer to how the real exam's second NFS server
    behaves.

Either way the provisioning does the same thing: install nfs-utils, create +
populate exports, write /etc/exports.d, run exportfs, enable nfs-server, open
the firewall. The config records which mode was used, and re-provision /
teardown around each exam dispatch to the right one so every run starts clean.

Design notes:
  * The provisioning scripts are defensive — they do NOT `set -e` and die on
    the first hiccup. They auto-create missing directories for *pre-existing*
    stale exports (so a leftover entry like `/nfsdata3` can't abort our run),
    tolerate unrelated exportfs warnings, and only report success once OUR
    exports are actually active. Failures come back as a single
    RHCSA_NFS_FAIL: <reason>.
  * Remote auth is delegated to the system `ssh`. Credentials may optionally
    be saved (root-only 0600 config) so exams can re-provision unattended;
    otherwise we rely on key-based auth. Local mode runs the identical script
    as a local root shell — no auth needed, we're already root.
"""

import os
import json
import shutil
import subprocess

STATE_DIR = '/var/lib/rhcsa-simulator'
CONFIG_PATH = os.path.join(STATE_DIR, 'nfs_server.conf')

LOCAL_HOST = 'localhost'

EXPORT_BASE = '/exports/rhcsa'
# (relative-name, export-options) — populated read/write so candidates can test.
_EXPORTS = [
    ('data', 'rw,sync,no_root_squash'),
    ('shared', 'rw,sync,no_root_squash'),
    ('public', 'ro,sync'),
    # Per-user home directories for the classic indirect/wildcard autofs task
    # (mount /home/guests/<user> from .../guests/<user> on demand).
    ('guests', 'rw,sync,no_root_squash'),
]

_DONE = 'RHCSA_NFS_DONE'
_FAIL = 'RHCSA_NFS_FAIL:'
_EXPORTS_LINE = 'RHCSA_NFS_EXPORTS='


# --------------------------------------------------------------------------
# Remote scripts
# --------------------------------------------------------------------------

def _seed_block():
    """Bash that (re)creates recognisable, relevant content in each export."""
    return f"""
stamp="provisioned by rhcsa-simulator on $(hostname -f 2>/dev/null || hostname) at $(date)"

rm -rf {EXPORT_BASE}/data {EXPORT_BASE}/shared {EXPORT_BASE}/public {EXPORT_BASE}/guests
mkdir -p {EXPORT_BASE}/data/archive {EXPORT_BASE}/public
# First-level subdirectories double as indirect-map keys (ls /shares/docs ...).
mkdir -p {EXPORT_BASE}/shared/projects {EXPORT_BASE}/shared/docs {EXPORT_BASE}/shared/tools
# Per-user homes for the wildcard automount task (/home/guests/<user>).
mkdir -p {EXPORT_BASE}/guests/user1 {EXPORT_BASE}/guests/user2 {EXPORT_BASE}/guests/user3

printf 'date,region,units,revenue\\n2026-01-15,EMEA,120,30450\\n2026-02-03,AMER,98,24010\\n2026-03-20,APAC,142,35980\\n' > {EXPORT_BASE}/data/sales-2026-q1.csv
printf 'widget-a 412\\nwidget-b 87\\nwidget-c 0\\n' > {EXPORT_BASE}/data/inventory.txt
printf 'old rotated log line 1\\nold rotated log line 2\\n' > {EXPORT_BASE}/data/archive/2025.log
printf 'NFS export: data (read-write)\\n%s\\n' "$stamp" > {EXPORT_BASE}/data/MANIFEST.txt

printf '# Team Roster\\nalice - lead\\nbob - sysadmin\\ncarol - dba\\n' > {EXPORT_BASE}/shared/team-roster.md
printf 'Standup notes: NFS migration on track.\\n' > {EXPORT_BASE}/shared/meeting-notes.txt
printf 'project alpha: active\\nproject beta: planning\\n' > {EXPORT_BASE}/shared/projects/status.txt
printf 'Onboarding guide\\nRunbook index\\n' > {EXPORT_BASE}/shared/docs/index.txt
printf 'backup.sh - nightly backup helper\\ncleanup.sh - tmp reaper\\n' > {EXPORT_BASE}/shared/tools/README.txt
printf 'NFS export: shared (read-write)\\n%s\\n' "$stamp" > {EXPORT_BASE}/shared/MANIFEST.txt

for u in user1 user2 user3; do
  printf 'Welcome %s! This home directory lives on the NFS server.\\n' "$u" > {EXPORT_BASE}/guests/$u/README.txt
  printf 'export PS1="[\\\\u@\\\\h \\\\W]\\\\$ "\\n' > {EXPORT_BASE}/guests/$u/.bashrc
done
printf 'NFS export: guests (read-write, per-user homes)\\n%s\\n' "$stamp" > {EXPORT_BASE}/guests/MANIFEST.txt

printf 'Welcome to the RHCSA practice NFS server.\\nThis share is read-only.\\n' > {EXPORT_BASE}/public/announcement.txt
printf 'rhcsa-simulator NFS v1\\n' > {EXPORT_BASE}/public/VERSION
printf 'NFS export: public (read-only)\\n%s\\n' "$stamp" > {EXPORT_BASE}/public/MANIFEST.txt

chmod -R 0777 {EXPORT_BASE}/data {EXPORT_BASE}/shared {EXPORT_BASE}/guests 2>/dev/null || true
chmod -R 0555 {EXPORT_BASE}/public 2>/dev/null || true
command -v restorecon >/dev/null 2>&1 && restorecon -R {EXPORT_BASE} 2>/dev/null || true
"""


def _provision_script():
    """Idempotent, self-correcting provisioning script (no `set -e`)."""
    exports_paths = [f'{EXPORT_BASE}/{name}' for name, _ in _EXPORTS]
    export_lines = "\n".join(f'{EXPORT_BASE}/{name} *({opts})' for name, opts in _EXPORTS)
    verify = "\n".join(
        f'exportfs -v | awk \'{{print $1}}\' | grep -qx {p} || missing="$missing {p}"'
        for p in exports_paths
    )
    return f"""
fail() {{ echo "{_FAIL} $*"; exit 1; }}
echo '== rhcsa-simulator: provisioning NFS server =='

# 1. nfs-utils
if ! rpm -q nfs-utils >/dev/null 2>&1; then
  echo '  installing nfs-utils...'
  dnf -y install nfs-utils >/dev/null 2>&1 || dnf -y install nfs-utils || \
    fail "could not install nfs-utils (check the server's repos/network)"
fi

# 2. our exports (content reseeded fresh)
{_seed_block()}

# 3. our exports drop-in (never touches an existing /etc/exports)
mkdir -p /etc/exports.d || fail "could not write /etc/exports.d"
cat > /etc/exports.d/rhcsa.exports <<'EOF'
{export_lines}
EOF

# 4. SELF-CORRECTION: create missing dirs for ANY pre-existing export entry so a
#    stale line (e.g. /nfsdata3) can't make `exportfs -ra` abort.
for p in $(awk '!/^#/ && NF {{print $1}}' /etc/exports /etc/exports.d/*.exports 2>/dev/null); do
  case "$p" in
    /*) if [ ! -d "$p" ]; then
          echo "  fixing stale export: creating missing dir $p"
          mkdir -p "$p" 2>/dev/null && {{ command -v restorecon >/dev/null 2>&1 && restorecon "$p" 2>/dev/null; }} || \
            echo "  (could not create $p; skipping it)"
        fi ;;
  esac
done

# 5. service + (re-)export, tolerating unrelated stale entries
systemctl enable --now nfs-server >/dev/null 2>&1 || fail "could not start nfs-server"
exportfs -ra 2>&1 | sed 's/^/  exportfs: /'

# 6. firewall (only if firewalld is active)
if systemctl is-active --quiet firewalld; then
  firewall-cmd --permanent --add-service=nfs >/dev/null 2>&1
  firewall-cmd --permanent --add-service=mountd >/dev/null 2>&1
  firewall-cmd --permanent --add-service=rpc-bind >/dev/null 2>&1
  firewall-cmd --reload >/dev/null 2>&1
fi

# 7. SUCCESS CRITERION: our exports must actually be active
missing=""
{verify}
[ -z "$missing" ] || fail "these exports are not active after exportfs:$missing"

echo '== active exports =='
exportfs -v || true
echo '{_EXPORTS_LINE}'{','.join(exports_paths)!r}
echo {_DONE}
"""


def _remove_script():
    """Remove ONLY our exports + content; leave everything else alone."""
    return f"""
echo '== rhcsa-simulator: removing NFS exports =='
rm -f /etc/exports.d/rhcsa.exports
exportfs -ra 2>&1 | sed 's/^/  exportfs: /' || true
rm -rf {EXPORT_BASE} 2>/dev/null || true
echo {_DONE}
"""


# --------------------------------------------------------------------------
# Config persistence (creds optional, stored root-only)
# --------------------------------------------------------------------------

def load_config():
    try:
        with open(CONFIG_PATH) as fh:
            return json.load(fh)
    except Exception:
        return None


def save_config(host, user, exports, password=None, local=False):
    os.makedirs(STATE_DIR, exist_ok=True)
    cfg = {'host': host, 'user': user, 'exports': exports}
    if local:
        cfg['local'] = True
    if password:
        cfg['password'] = password
    # Open 0600 from the start so a saved password is never world-readable.
    fd = os.open(CONFIG_PATH, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, 'w') as fh:
        json.dump(cfg, fh, indent=2)
    try:
        os.chmod(CONFIG_PATH, 0o600)
    except OSError:
        pass
    return cfg


def clear_config():
    try:
        os.remove(CONFIG_PATH)
        return True
    except FileNotFoundError:
        return False


def get_server():
    cfg = load_config()
    return cfg.get('host') if cfg else None


def pick_export(cfg=None, index=0):
    cfg = cfg or load_config()
    if not cfg or not cfg.get('exports'):
        return None
    return cfg['exports'][index % len(cfg['exports'])]


# --------------------------------------------------------------------------
# SSH plumbing
# --------------------------------------------------------------------------

def _ssh_cmd(host, user, password=None, batch=False):
    """Build the ssh command. With a password, route through sshpass and force
    password auth; with batch=True (unattended), fail fast instead of hanging on
    a prompt."""
    cmd = []
    if password:
        cmd += ['sshpass', '-p', password]
    cmd += ['ssh', '-o', 'StrictHostKeyChecking=accept-new',
            '-o', 'ConnectTimeout=15']
    if password:
        cmd += ['-o', 'PreferredAuthentications=password',
                '-o', 'PubkeyAuthentication=no']
    elif batch:
        cmd += ['-o', 'BatchMode=yes']
    cmd += [f'{user}@{host}', 'bash -s']
    return cmd


def _run_remote(script, host, user, password=None, batch=False, timeout=600):
    """Feed `script` to the remote shell. ssh reads auth from the tty (not
    stdin), so piping the script in is safe even for interactive password entry.
    Returns (returncode, combined_output) or (None, message) on launch error."""
    cmd = _ssh_cmd(host, user, password, batch)
    try:
        res = subprocess.run(cmd, input=script, text=True,
                             capture_output=True, timeout=timeout)
        return res.returncode, (res.stdout or '') + (res.stderr or '')
    except FileNotFoundError:
        missing = 'sshpass' if password else 'ssh'
        return None, (f"'{missing}' not found on this machine."
                      + (" Install it (dnf install sshpass) or use key-based auth."
                         if password else ''))
    except subprocess.TimeoutExpired:
        return None, f'Timed out talking to {host}.'


def _parse(rc, output):
    """Interpret remote output: (ok, exports, output)."""
    if rc is None:
        return False, [], output
    if _DONE not in output:
        reason = next((ln[len(_FAIL):].strip()
                       for ln in output.splitlines() if ln.startswith(_FAIL)), '')
        if reason:
            return False, [], f"{reason}\n\n--- full output ---\n{output}"
        return False, [], output
    exports = []
    for line in output.splitlines():
        if line.startswith(_EXPORTS_LINE):
            raw = line[len(_EXPORTS_LINE):].strip().strip("'\"")
            exports = [p for p in raw.split(',') if p]
            break
    if not exports:
        exports = [f'{EXPORT_BASE}/{name}' for name, _ in _EXPORTS]
    return True, exports, output


def _run_local(script, timeout=600):
    """Run `script` as a local root shell — same contract as _run_remote
    (returns (returncode, combined_output) or (None, message) on launch
    error), just without SSH in the way."""
    try:
        res = subprocess.run(['bash', '-s'], input=script, text=True,
                             capture_output=True, timeout=timeout)
        return res.returncode, (res.stdout or '') + (res.stderr or '')
    except subprocess.TimeoutExpired:
        return None, 'Timed out provisioning the local NFS server.'


def provision_local():
    """Provision (or re-provision) THIS machine as its own NFS server — no
    second box needed. Returns (ok, exports, output)."""
    rc, out = _run_local(_provision_script())
    return _parse(rc, out)


def remove_local_exports():
    """Tear our exports down on this machine. Returns (ok, output)."""
    rc, out = _run_local(_remove_script())
    return (rc == 0 and _DONE in out), out


def copy_ssh_key(host, user):
    """Best-effort ssh-copy-id so subsequent runs are passwordless. Interactive."""
    try:
        return subprocess.run(['ssh-copy-id', f'{user}@{host}']).returncode == 0
    except FileNotFoundError:
        return False


def provision(host, user='root', password=None, batch=False):
    """Provision (or re-provision) the server. Returns (ok, exports, output)."""
    rc, out = _run_remote(_provision_script(), host, user, password, batch=batch)
    return _parse(rc, out)


def unmount_client_mounts(host=None):
    """Unmount LOCAL nfs mounts served by our configured server BEFORE the
    server's exports are removed, so they never become stale (a stale NFS mount
    makes stat()/cleanup hang on the next exam). Matches by server host or by an
    export path we own (handles name-vs-IP mismatches). Returns the count.

    All operations are timeout-bounded; a 'umount -l' is lazy so it returns
    immediately even if a mount is already unreachable.
    """
    cfg = load_config()
    if host is None:
        host = cfg.get('host') if cfg else None
    exports = set(cfg.get('exports', [])) if cfg else set()
    if not host and not exports:
        return 0

    try:
        res = subprocess.run(
            ['findmnt', '-rno', 'TARGET,SOURCE', '-t', 'nfs,nfs4'],
            capture_output=True, text=True, timeout=15
        )
    except Exception:
        return 0

    count = 0
    for line in res.stdout.splitlines():
        parts = line.split()
        if len(parts) < 2:
            continue
        target, source = parts[0], parts[1]
        src_host, _, src_path = source.partition(':')
        if (host and src_host == host) or (src_path and src_path in exports):
            try:
                subprocess.run(['umount', '-l', '--', target],
                               capture_output=True, timeout=15)
                count += 1
            except Exception:
                pass
    return count


def remove_exports(host=None, user='root', password=None, batch=True):
    """Tear our exports down on the server (local or remote). Returns (ok, output)."""
    cfg = load_config()
    if cfg and cfg.get('local') and host is None:
        return remove_local_exports()
    if host is None:
        if not cfg:
            return False, 'no NFS server configured'
        host, user = cfg['host'], cfg.get('user', 'root')
        password = password or cfg.get('password')
    rc, out = _run_remote(_remove_script(), host, user, password, batch=batch)
    return (rc == 0 and _DONE in out), out


def reprovision_from_config(batch=True):
    """Re-provision using the saved config — local or remote (unattended exam
    refresh). Returns (ok, exports_or_None, output) or (None, None, reason)
    if unusable."""
    cfg = load_config()
    if not cfg:
        return None, None, 'no NFS server configured'
    if cfg.get('local'):
        return provision_local()
    pw = cfg.get('password')
    # Unattended: needs a saved password OR key-based auth (batch mode).
    ok, exports, out = provision(cfg['host'], cfg.get('user', 'root'),
                                 password=pw, batch=(pw is None))
    return ok, (exports if ok else None), out


def sshpass_available():
    return shutil.which('sshpass') is not None


def verify_from_client(host):
    """showmount -e against the server from this machine. (ok, output)."""
    try:
        res = subprocess.run(['showmount', '-e', host],
                             capture_output=True, text=True, timeout=30)
        return res.returncode == 0, (res.stdout or res.stderr).strip()
    except FileNotFoundError:
        return False, "'showmount' not installed (dnf install nfs-utils)."
    except subprocess.TimeoutExpired:
        return False, 'showmount timed out (firewall? nfs-server not running?).'
