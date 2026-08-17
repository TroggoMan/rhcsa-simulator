"""
Checker dispute reporting.

When a candidate reviewing their results believes a validator (the "checker")
scored a task incorrectly, they can dispute it from the result detail screen.
A dispute:

  1. captures the relevant LIVE system state as evidence (category-specific
     diagnostic commands, plus any commands the candidate supplies),
  2. bundles it with the task, the disputed check(s) and the candidate's
     written argument into a Markdown report,
  3. opens a GitHub issue (labelled ``checker-dispute``) via the ``gh`` CLI.

A GitHub Action (.github/workflows/checker-dispute.yml) reacts to that label:
an AI reviewer inspects the validator for the task, compares it against the
uploaded evidence, comments its verdict, and — if the checker is genuinely
wrong — opens a fix PR automatically.

Nothing here changes system state; it only reads it.
"""

import os
import shutil
import subprocess
import urllib.parse
from datetime import datetime

from utils import formatters as fmt  # noqa: F401  (kept for callers/consistency)


# Repo root = parent of this package directory; gh / git run from here.
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DISPUTE_DIR = os.path.join(REPO_ROOT, 'data', 'disputes')
DISPUTE_LABEL = 'checker-dispute'

# Used to build the browser fallback URL when the git remote can't be read
# (e.g. a tarball copy on an exam box with no origin remote).
GITHUB_REPO_FALLBACK = 'TroggoMan/rhcsa-simulator'

_MAX_OUTPUT = 4000  # chars kept per command, to keep issues readable

# Always-captured baseline context.
_GENERIC_EVIDENCE = [
    ['uname', '-r'],
    ['sh', '-c', 'cat /etc/os-release 2>/dev/null | head -5'],
]

# Category -> read-only diagnostic commands that show the relevant state.
_CATEGORY_EVIDENCE = {
    'swap': [['swapon', '--show'], ['cat', '/proc/swaps'], ['lsblk', '-f'],
             ['blkid'], ['sh', '-c', 'grep -i swap /etc/fstab']],
    'lvm': [['pvs'], ['vgs'], ['lvs'], ['lsblk'], ['cat', '/etc/fstab']],
    'partitioning': [['lsblk', '-f'], ['blkid'], ['cat', '/etc/fstab']],
    'filesystems': [['lsblk', '-f'], ['blkid'], ['findmnt', '--real'],
                    ['cat', '/etc/fstab']],
    'repos': [['dnf', 'repolist', '--all'],
              ['sh', '-c', 'ls -la /etc/yum.repos.d/'],
              ['sh', '-c', 'tail -n +1 /etc/yum.repos.d/*.repo']],
    'users_groups': [['sh', '-c', 'getent passwd | tail -20'],
                     ['sh', '-c', 'getent group | tail -20'],
                     ['sh', '-c', 'grep -E "PASS_MAX|PASS_MIN|PASS_WARN" /etc/login.defs']],
    'selinux': [['getenforce'], ['sh', '-c', 'sestatus 2>/dev/null']],
    'networking': [['sh', '-c', 'nmcli -t con show 2>/dev/null'],
                   ['sh', '-c', 'ip -br a'], ['cat', '/etc/resolv.conf']],
    'services': [['sh', '-c', 'systemctl list-units --type=service --no-pager | head -40']],
    'firewall': [['sh', '-c', 'firewall-cmd --list-all 2>/dev/null']],
    'boot': [['cat', '/proc/cmdline'], ['sh', '-c', 'ls -la /boot/grub2/ 2>/dev/null']],
    'scheduling': [['sh', '-c', 'systemctl list-timers --no-pager'],
                   ['sh', '-c', 'crontab -l 2>/dev/null']],
    'systemd_timers': [['sh', '-c', 'systemctl list-timers --all --no-pager | head -40']],
    'ssh': [['sh', '-c', 'sshd -T 2>/dev/null | head -40'],
            ['sh', '-c', 'ls -la ~/.ssh 2>/dev/null']],
    'permissions': [['sh', '-c', 'echo "(provide the path with a custom command below)"']],
    'packages': [['sh', '-c', 'rpm -qa | wc -l']],
}


def _run(cmd, shell=False):
    """Run a diagnostic command, returning (display, rc, output) truncated."""
    display = cmd if isinstance(cmd, str) else ' '.join(cmd)
    try:
        res = subprocess.run(
            cmd, shell=shell, capture_output=True, text=True, timeout=25,
            cwd='/'
        )
        out = (res.stdout or '') + (res.stderr or '')
        out = out.strip()
        if len(out) > _MAX_OUTPUT:
            out = out[:_MAX_OUTPUT] + '\n...[truncated]...'
        return display, res.returncode, out or '(no output)'
    except FileNotFoundError:
        return display, 127, '(command not found)'
    except subprocess.TimeoutExpired:
        return display, 124, '(timed out)'
    except Exception as e:
        return display, 1, f'(error: {e})'


def gh_available():
    """True if the gh CLI is installed and authenticated for this repo."""
    if not shutil.which('gh'):
        return False
    try:
        res = subprocess.run(['gh', 'auth', 'status'],
                             capture_output=True, text=True, timeout=15)
        return res.returncode == 0
    except Exception:
        return False


def repo_slug():
    """Return 'owner/repo' from the git origin remote, or a sensible fallback.

    Works for both SSH (git@github.com:owner/repo.git) and HTTPS remotes; falls
    back to GITHUB_REPO_FALLBACK when there's no git remote (tarball copy).
    """
    try:
        res = subprocess.run(['git', 'remote', 'get-url', 'origin'],
                             capture_output=True, text=True, cwd=REPO_ROOT, timeout=10)
        url = (res.stdout or '').strip()
        if url:
            if url.startswith('git@') or ('@' in url and '://' not in url):
                path = url.split(':', 1)[1] if ':' in url else url
            else:
                path = urllib.parse.urlsplit(url).path
            path = path.strip('/')
            if path.endswith('.git'):
                path = path[:-4]
            if path and '/' in path:
                return path
    except Exception:
        pass
    return GITHUB_REPO_FALLBACK


def issue_url(tr, body, max_url=7000):
    """Build a pre-filled GitHub 'new issue' URL — no gh, no auth on this box.

    The candidate opens it in any browser where they're logged into GitHub and
    just clicks 'Submit'. GitHub truncates very long GET URLs, so if the full
    report doesn't fit the body is trimmed (the complete report is always kept
    locally by save_report()).
    """
    title = f"[checker dispute] {tr.get('task_id', 'task')}: scored " \
            f"{tr.get('score', '?')}/{tr.get('max_score', '?')}"
    base = f"https://github.com/{repo_slug()}/issues/new"

    def build(b):
        q = urllib.parse.urlencode(
            {'title': title, 'body': b, 'labels': DISPUTE_LABEL})
        return f"{base}?{q}"

    url = build(body)
    if len(url) <= max_url:
        return url

    note = ("\n\n_(Evidence truncated to fit the URL — the full report is saved "
            "on the exam host; paste it in if you can.)_")
    budget = len(body)
    while budget > 400:
        budget = int(budget * 0.8)
        url = build(body[:budget] + note)
        if len(url) <= max_url:
            return url
    return build(title)  # extreme fallback: title only


def resolve_source(category, task_id):
    """Locate the task's source so the reviewer opens ONE file, not the repo.

    Returns (relpath, classname, validate_line) or (None, None, None). Task ids
    are assigned in __init__, so we instantiate candidate classes (cheap; no
    generate()) and match on .id.
    """
    try:
        import inspect
        from tasks.registry import TaskRegistry
        TaskRegistry.initialize()

        classes = list(TaskRegistry.get_tasks_by_category(category) or [])
        if not classes:  # unknown/blank category — fall back to a full scan
            for cat in TaskRegistry.get_all_categories():
                classes.extend(TaskRegistry.get_tasks_by_category(cat))

        for cls in classes:
            try:
                if getattr(cls(), 'id', None) != task_id:
                    continue
            except Exception:
                continue
            src = inspect.getsourcefile(cls) or inspect.getfile(cls)
            rel = os.path.relpath(src, REPO_ROOT)
            line = None
            try:
                line = inspect.getsourcelines(cls.validate)[1]
            except Exception:
                pass
            return rel, cls.__name__, line
    except Exception:
        pass
    return None, None, None


def collect_evidence(category, extra_commands=None):
    """Gather (display, rc, output) tuples for the category + any extra commands."""
    evidence = []
    for cmd in _GENERIC_EVIDENCE:
        evidence.append(_run(cmd))
    for cmd in _CATEGORY_EVIDENCE.get(category, []):
        evidence.append(_run(cmd))
    for raw in (extra_commands or []):
        raw = raw.strip()
        if raw:
            evidence.append(_run(raw, shell=True))
    return evidence


def build_report(tr, disputed, argument, evidence):
    """Render the dispute as Markdown for the GitHub issue body."""
    lines = []
    lines.append(f"## Checker dispute: `{tr.get('task_id', '?')}`")
    lines.append("")
    lines.append(f"- **Task ID:** `{tr.get('task_id', '?')}`")
    lines.append(f"- **Category:** {tr.get('category', '?')}")
    lines.append(f"- **Difficulty:** {tr.get('difficulty', '?')}")
    lines.append(f"- **Scored:** {tr.get('score', '?')}/{tr.get('max_score', '?')} "
                 f"({'PASSED' if tr.get('passed') else 'FAILED'})")
    lines.append(f"- **Filed:** {datetime.now().isoformat(timespec='seconds')}")
    # Point the reviewer straight at the checker so it reads one file, not the
    # whole repo (keeps the review cheap).
    rel, classname, vline = resolve_source(tr.get('category', ''), tr.get('task_id', ''))
    if rel:
        loc = f"`{rel}` → class `{classname}`"
        if vline:
            loc += f", `validate()` around line {vline}"
        lines.append(f"- **Checker source:** {loc}")
    lines.append("")
    lines.append("### Task as presented to the candidate")
    lines.append("```")
    lines.append(tr.get('description') or '(no description saved)')
    lines.append("```")
    lines.append("")
    lines.append("### Disputed check(s) — candidate says these are WRONG")
    for c in disputed:
        mark = '✓' if c.get('passed') else '✗'
        lines.append(f"- {mark} [{c.get('points', 0)}/{c.get('max_points', c.get('points', 0))}pt] "
                     f"{c.get('message', c.get('name', ''))}")
    lines.append("")
    lines.append("### Candidate's argument")
    lines.append("")
    lines.append(argument.strip() or '(none provided)')
    lines.append("")
    lines.append("### Captured system state (evidence)")
    for display, rc, out in evidence:
        lines.append("")
        lines.append(f"<details><summary><code>$ {display}</code> (rc={rc})</summary>")
        lines.append("")
        lines.append("```")
        lines.append(out)
        lines.append("```")
        lines.append("</details>")
    lines.append("")
    lines.append("---")
    lines.append(
        "_Filed automatically from the RHCSA simulator. An AI reviewer will "
        f"inspect the validator for `{tr.get('task_id', '?')}`, compare it "
        "against the evidence above, comment a verdict, and open a fix PR if "
        "the checker is found to be wrong._"
    )
    return "\n".join(lines)


def save_report(tr, body):
    """Persist the report locally and return its path."""
    os.makedirs(DISPUTE_DIR, exist_ok=True)
    stamp = datetime.now().strftime('%Y%m%d-%H%M%S')
    path = os.path.join(DISPUTE_DIR, f"{tr.get('task_id', 'task')}-{stamp}.md")
    with open(path, 'w') as fh:
        fh.write(body)
    return path


def submit_issue(tr, body_path):
    """Open a labelled GitHub issue from the saved report. Returns (ok, info)."""
    title = f"[checker dispute] {tr.get('task_id', 'task')}: scored " \
            f"{tr.get('score', '?')}/{tr.get('max_score', '?')}"

    # Best-effort: make sure the label exists (ignore "already exists").
    subprocess.run(
        ['gh', 'label', 'create', DISPUTE_LABEL, '--color', 'D93F0B',
         '--description', 'Candidate disputes a validator result',
         '--force'],
        capture_output=True, text=True, cwd=REPO_ROOT, timeout=20
    )

    cmd = ['gh', 'issue', 'create', '--title', title,
           '--body-file', body_path, '--label', DISPUTE_LABEL]
    res = subprocess.run(cmd, capture_output=True, text=True,
                         cwd=REPO_ROOT, timeout=60)
    if res.returncode == 0:
        url = res.stdout.strip().splitlines()[-1] if res.stdout.strip() else ''
        return True, url
    # Retry without the label in case label creation was not permitted.
    res2 = subprocess.run(
        ['gh', 'issue', 'create', '--title', title, '--body-file', body_path],
        capture_output=True, text=True, cwd=REPO_ROOT, timeout=60
    )
    if res2.returncode == 0:
        url = res2.stdout.strip().splitlines()[-1] if res2.stdout.strip() else ''
        return True, url + " (label not applied — add it manually to trigger the AI review)"
    return False, (res.stderr or res2.stderr or 'gh issue create failed').strip()
