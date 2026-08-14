"""
Exam task panel — the question sheet as a separate window you manage.

WHY
---
On the real EX200 the tasks live in a window of their own on the exam
desktop — Red Hat's own application, not a browser and not your terminal:
a checklist you tick off, with each task's detail hidden until you open it.
You read one, alt-tab away, work, alt-tab back, lose your place, scroll,
and repeat that twenty times under a clock. Candidates consistently report
that juggling that window is its own skill, separate from knowing the
material — so practising against a scrollable pager in the same terminal
you're working in trains the wrong thing.

We reproduce the shape of that, not the technology: the live task sheet is
served over HTTP so it can sit in a window beside your terminals, the way
it will on the day. HTTP is simply the one way to put a window on screen
that needs nothing installed and works when the exam VM is headless.

SHAPE
-----
An accordion, in a modern skin: a sidebar carrying the countdown and a
done/revisit tally, a "perform these tasks on <host>" chip, then one
collapsed row per task. Click a row and its drawer expands in place to
reveal the task text.

Row labels are deliberately generic ("Task 07") — exactly as on the day,
you cannot triage the list by reading it, you have to open each one.

Each task carries **Revisit** and **Done**. They toggle independently:
click again to clear, and a task can be both (you did something, but want
another look).

No Red Hat branding — this is a practice tool and must not present itself
as the real exam.

Marks are advisory bookkeeping for the candidate. Ticking "done" does not
tell the grader anything — validation still runs against real system state
in the terminal, exactly as before. That separation is deliberate: the
panel must never become a way to score points.

DESIGN
------
- Stdlib only (http.server + json), consistent with the rest of the project.
- The panel drives the session: submit for grading, read the per-check
  results, dispute a check, reset the lab. Those are real actions on a real
  box, which is why every request is authenticated (see below) — an earlier
  version of this panel was read-only and could afford not to be.

AUTHENTICATION
--------------
A random token is minted per session and embedded in the URL the exam
prints. Every request must carry it, as ?t= or an X-Panel-Token header;
anything else gets 403. This exists because the panel binds 0.0.0.0 by
default so a headless exam VM can be read from a laptop — and once the
panel can reset the lab or file a GitHub issue, "anyone who can reach the
port" is no longer an acceptable authorisation rule. The token is compared
with secrets.compare_digest.

Reset is additionally guarded server-side: it refuses while an exam is
running unless the caller passes confirm=True, so a stray request cannot
wipe a session in progress.
- Marks live server-side so the view survives a page reload and is shared
  across windows (laptop and phone show the same ticks).
- The page holds no state worth losing: it polls /api/state and re-renders.
- Runs on a daemon thread. A dead or hung panel must never hold up an exam,
  so every failure path degrades to "no panel" rather than raising.
"""

import json
import logging
import secrets
import socket
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

logger = logging.getLogger(__name__)

DEFAULT_PORT = 8080

MARK_FIELDS = ('done', 'revisit')

# Per-session and deliberately in-memory. These are the exam's own "done" /
# "revisit" ticks, NOT core.task_flags (which reports a task as *defective*
# and persists to disk for the maintainer). Conflating them would let a
# candidate silently file bug reports against tasks they merely found hard.
_marks = {}


def _domain_name(task):
    try:
        from config import settings
        return settings.EXAM_DOMAINS.get(getattr(task, 'exam_domain', 0), '')
    except Exception:
        return ''


def _local_host():
    try:
        name = socket.getfqdn()
        return name if name and name != 'localhost' else socket.gethostname()
    except Exception:
        return 'this system'


def _target_host(task):
    """Which machine this task is performed on.

    The real exam groups its sheet by node ("Perform the following tasks on
    node1.domain14.example.com"), so tasks that run against the optional lab
    machine are grouped separately from the ones on this box.
    """
    if getattr(task, 'requires_lab_machine', False):
        try:
            from core import lab_machine
            host = lab_machine.get_host()
            if host:
                return host
        except Exception:
            pass
        return 'the lab machine'
    return _local_host()


def _category_label(task):
    """Human-readable category — this is all the candidate sees until they
    open the task, so it has to be meaningful on its own."""
    try:
        from utils.formatters import format_category_name
        return format_category_name(getattr(task, 'category', '') or '')
    except Exception:
        return (getattr(task, 'category', '') or '').replace('_', ' ').title()


def marks_for(task_id):
    """Current ticks for a task, defaulted."""
    m = _marks.get(task_id) or {}
    return {f: bool(m.get(f)) for f in MARK_FIELDS}


def set_mark(task_id, field, value):
    """Tick/untick one box. Returns the task's full mark state.

    'done' and 'revisit' are independent on purpose — mid-exam you often
    want both on the same task ("I did something, but come back to it").
    """
    if not task_id or field not in MARK_FIELDS:
        raise ValueError('unknown mark field')
    current = dict(marks_for(task_id))
    current[field] = bool(value)
    _marks[task_id] = current
    return current


def clear_marks():
    _marks.clear()


def build_state(tasks, remaining_seconds=None):
    """Serialisable snapshot of the exam for the panel.

    Pure and side-effect free so it can be tested without a server.
    """
    items = []
    for i, task in enumerate(tasks or [], 1):
        task_id = getattr(task, 'id', '') or ''
        m = marks_for(task_id)
        items.append({
            'n': i,
            'id': task_id,
            'description': getattr(task, 'description', '') or '',
            'points': getattr(task, 'points', 0) or 0,
            'domain': getattr(task, 'exam_domain', 0) or 0,
            'domain_name': _domain_name(task),
            'category': _category_label(task),
            'host': _target_host(task),
            'done': m['done'],
            'revisit': m['revisit'],
        })
    return {
        'tasks': items,
        'count': len(items),
        'total_points': sum(t['points'] for t in items),
        'done_count': sum(1 for t in items if t['done']),
        'revisit_count': sum(1 for t in items if t['revisit']),
        'remaining_seconds': remaining_seconds,
    }


def _probe(cmd, timeout=5):
    """Run a read-only command, returning stdout or None. Never raises."""
    import subprocess
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except (FileNotFoundError, OSError, Exception):
        return None
    return r.stdout if r.returncode == 0 else None


# Addresses that are never a useful URL for the candidate's browser.
# 192.0.2.0/24 and friends matter here specifically because the simulator's
# own networking tasks configure documentation-range addresses on dummy
# interfaces — this used to advertise http://192.0.2.10:8080/ on a box that
# had run one.
_USELESS_ADDR_PREFIXES = (
    '127.',          # loopback, already listed
    '169.254.',      # link-local
    '192.0.2.',      # TEST-NET-1
    '198.51.100.',   # TEST-NET-2
    '203.0.113.',    # TEST-NET-3
)


def _host_addresses():
    """Global-scope IPv4 addresses another machine could actually reach."""
    found = []
    out = _probe(['ip', '-4', '-o', 'addr', 'show', 'scope', 'global'])
    if out:
        for line in out.splitlines():
            parts = line.split()
            for i, token in enumerate(parts):
                if token == 'inet' and i + 1 < len(parts):
                    found.append(parts[i + 1].split('/')[0])
    if not found:
        # No iproute2: ask the kernel which source address it would use for
        # an off-box destination. No packets are sent by connecting a UDP
        # socket — it only sets the local endpoint.
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            try:
                s.connect(('8.8.8.8', 9))
                found.append(s.getsockname()[0])
            finally:
                s.close()
        except OSError:
            pass
    return [a for a in found if a and not a.startswith(_USELESS_ADDR_PREFIXES)]


def firewall_blocks(port):
    """True if firewalld is running and would drop connections to `port`.

    Deliberately advisory. The panel must NEVER open the port itself: this
    simulator has firewall tasks, and silently editing firewalld would
    corrupt the very state their validators grade.
    """
    active = _probe(['systemctl', 'is-active', 'firewalld'])
    if not active or active.strip() != 'active':
        return False
    ports = _probe(['firewall-cmd', '--list-ports'])
    if ports is None:
        return False
    return ('%d/tcp' % port) not in ports.split()


def _local_addresses(port):
    """URLs the panel is reachable on, best-effort. The LAN address matters:
    the exam VM is usually headless, so the browser is on another machine."""
    urls = ['http://127.0.0.1:%d/' % port]
    urls.extend('http://%s:%d/' % (a, port) for a in _host_addresses())
    return urls


def _json_body(handler):
    """Parse a JSON request body. Returns {} on anything unreadable."""
    try:
        length = int(handler.headers.get('Content-Length') or 0)
        if length <= 0:
            return {}
        return json.loads(handler.rfile.read(length) or b'{}')
    except (ValueError, TypeError, OSError):
        return {}


class _Handler(BaseHTTPRequestHandler):
    server_version = 'RHCSATaskPanel/1.0'

    # Silence per-request logging; an exam console must stay readable.
    def log_message(self, fmt_, *args):
        logger.debug("task_gui: " + fmt_, *args)

    def _send(self, code, body, content_type):
        if isinstance(body, str):
            body = body.encode('utf-8')
        self.send_response(code)
        self.send_header('Content-Type', content_type)
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'no-store')
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            pass  # browser navigated away mid-response

    def _authorized(self):
        """Every request must carry the session token.

        The panel binds 0.0.0.0 so a headless VM can be read from a laptop.
        Now that it can submit for grading, file a GitHub issue and reset the
        lab, "can reach the port" is not an acceptable authorisation rule.
        """
        expected = getattr(self.server, 'token', None)
        if not expected:
            return True                      # token disabled (tests)
        supplied = self.headers.get('X-Panel-Token') or ''
        if not supplied and '?' in self.path:
            from urllib.parse import parse_qs, urlparse
            supplied = (parse_qs(urlparse(self.path).query).get('t') or [''])[0]
        return secrets.compare_digest(str(supplied), str(expected))

    def _deny(self):
        self._send(403, '{"error":"invalid or missing panel token"}',
                   'application/json')

    def _action(self, name, *args, **kwargs):
        """Call a controller method, returning (status_code, payload).

        A panel wired without a controller (or to one missing this action)
        answers 501 rather than pretending the action happened.
        """
        controller = getattr(self.server, 'controller', None)
        fn = getattr(controller, name, None) if controller else None
        if fn is None:
            return 501, {'error': f'{name} is not available in this session'}
        try:
            return 200, fn(*args, **kwargs)
        except Exception as e:                        # controller bugs
            logger.warning("panel action %s failed: %s", name, e)
            return 500, {'error': str(e)}

    def do_GET(self):
        path = self.path.split('?', 1)[0].rstrip('/') or '/'
        if not self._authorized():
            return self._deny()

        if path == '/':
            self._send(200, PAGE_HTML, 'text/html; charset=utf-8')
        elif path == '/api/state':
            try:
                state = self.server.state_provider()
            except Exception as e:
                logger.debug("state_provider failed: %s", e)
                state = {'tasks': [], 'count': 0, 'total_points': 0,
                         'done_count': 0, 'revisit_count': 0,
                         'remaining_seconds': None, 'error': 'state unavailable'}
            self._send(200, json.dumps(state), 'application/json')
        elif path == '/api/disputes':
            code, payload = self._action('list_disputes')
            self._send(code, json.dumps(payload), 'application/json')
        else:
            self._send(404, '{"error":"not found"}', 'application/json')

    def do_POST(self):
        path = self.path.split('?', 1)[0].rstrip('/') or '/'
        if not self._authorized():
            return self._deny()

        if path == '/api/mark':
            payload = _json_body(self)
            try:
                state = set_mark(payload.get('id'), payload.get('field'),
                                 bool(payload.get('value')))
            except ValueError:
                self._send(400, '{"error":"unknown mark"}', 'application/json')
                return
            self._send(200, json.dumps({'id': payload.get('id'),
                                        'marks': state}), 'application/json')

        elif path == '/api/validate':
            # Submit for grading. The controller queues it for the main
            # thread — validators run real commands and touch shared session
            # state, so they must not run on an HTTP worker thread.
            code, payload = self._action('request_validate')
            self._send(code, json.dumps(payload), 'application/json')

        elif path == '/api/dispute':
            body = _json_body(self)
            code, payload = self._action(
                'file_dispute',
                task_id=body.get('task_id'),
                check_names=body.get('checks') or [],
                argument=body.get('argument') or '',
                submit=bool(body.get('submit', True)),
            )
            self._send(code, json.dumps(payload), 'application/json')

        elif path == '/api/reset-lab':
            body = _json_body(self)
            code, payload = self._action('reset_lab',
                                         confirm=bool(body.get('confirm')))
            self._send(code, json.dumps(payload), 'application/json')

        else:
            self._send(404, '{"error":"not found"}', 'application/json')


class TaskPanel:
    """Background HTTP server showing the current exam's task sheet."""

    def __init__(self, state_provider, controller=None, port=DEFAULT_PORT,
                 bind='0.0.0.0', token=None):
        self.state_provider = state_provider
        # Optional: object exposing request_validate / file_dispute /
        # reset_lab / list_disputes. Without it those endpoints answer 501.
        self.controller = controller
        self.port = port
        self.bind = bind
        # Pass token='' to disable auth (tests only). Otherwise every request
        # must present this value.
        self.token = secrets.token_urlsafe(16) if token is None else token
        self._httpd = None
        self._thread = None

    @property
    def running(self):
        return self._httpd is not None

    def start(self):
        """Start serving. Returns the list of URLs, or [] if it couldn't
        start — a panel that won't bind must not stop the exam."""
        if self.running:
            return self.urls()
        try:
            httpd = ThreadingHTTPServer((self.bind, self.port), _Handler)
        except OSError as e:
            logger.warning("task panel could not bind %s:%s — %s",
                           self.bind, self.port, e)
            return []
        httpd.state_provider = self.state_provider
        httpd.controller = self.controller
        httpd.token = self.token
        httpd.daemon_threads = True
        self._httpd = httpd
        self._thread = threading.Thread(target=httpd.serve_forever,
                                        name='rhcsa-task-panel', daemon=True)
        self._thread.start()
        return self.urls()

    def urls(self):
        """Reachable URLs, each carrying the session token.

        The token is in the URL rather than a separate secret to type,
        because an exam candidate should be able to click once and start.
        """
        if not self.running:
            return []
        port = self._httpd.server_address[1]
        suffix = ('?t=%s' % self.token) if self.token else ''
        if self.bind in ('127.0.0.1', 'localhost'):
            bases = ['http://127.0.0.1:%d/' % port]
        else:
            bases = _local_addresses(port)
        return [b + suffix for b in bases]

    def stop(self):
        if not self.running:
            return
        try:
            self._httpd.shutdown()
            self._httpd.server_close()
        except Exception as e:
            logger.debug("task panel shutdown: %s", e)
        finally:
            self._httpd = None
            self._thread = None


def start_for_session(session, controller=None, port=DEFAULT_PORT,
                      bind='0.0.0.0'):
    """Start a panel backed by a live ExamSession. Never raises."""
    def provider():
        remaining = None
        try:
            from core import exam_clock
            remaining = exam_clock.remaining_seconds()
        except Exception:
            pass
        state = build_state(getattr(session, 'tasks', []), remaining)
        # Grading state lives on the session so the panel and the terminal
        # always agree about what has been submitted and what it scored.
        state['status'] = getattr(session, 'panel_status', 'in_progress')
        state['results'] = getattr(session, 'panel_results', None)
        state['can_control'] = controller is not None
        return state

    try:
        panel = TaskPanel(provider, controller=controller, port=port, bind=bind)
        urls = panel.start()
        return (panel, urls) if urls else (None, [])
    except Exception as e:
        logger.warning("task panel failed to start: %s", e)
        return (None, [])


class _TaskListSession:
    """Minimal `.tasks` provider so start_for_tasks() can reuse
    start_for_session() for a plain task list — quick/practice/adaptive/learn
    have no ExamSession, just the tasks themselves."""

    def __init__(self, get_tasks):
        self._get_tasks = get_tasks

    @property
    def tasks(self):
        return self._get_tasks()


def start_for_tasks(get_tasks, port=DEFAULT_PORT, bind='0.0.0.0'):
    """Start a panel backed by a callable returning the current task list.
    Never raises."""
    return start_for_session(_TaskListSession(get_tasks), port=port, bind=bind)


def open_panel(tasks, port, bind='0.0.0.0'):
    """Start the task panel for a session's task list and print how to reach
    it. Shared by every mode (exam/quick/practice/adaptive/learn) so the
    panel is the same default experience everywhere, with the terminal as
    the automatic fallback: a panel that won't start must never stop a
    session, it just prints a warning and the caller carries on without it.
    Returns the running TaskPanel, or None if disabled or it failed to bind.
    """
    if not port:
        return None
    from utils import formatters as fmt
    clear_marks()
    panel, urls = start_for_tasks(lambda: tasks, port=port, bind=bind)
    if not urls:
        print(fmt.warning(
            f"\nTask panel could not start on port {port} (in use?). "
            f"Continuing in the terminal — the task text below is the same "
            f"content."))
        return None
    print()
    print(fmt.success("Task panel running — open it beside your terminals:"))
    for url in urls:
        print(fmt.bold(f"    {url}"))
    if bind not in ('127.0.0.1', 'localhost'):
        print(fmt.dim("  (Unauthenticated and reachable from your LAN. It "
                      "serves the task sheet only — no shell, no control "
                      "of this box.)"))
        # A stock RHEL/Alma box has firewalld up with nothing open, so the
        # LAN URL above simply won't connect from a laptop. Say so rather
        # than letting the candidate debug it mid-session. We never open the
        # port ourselves — this simulator grades firewall tasks, and editing
        # firewalld here would corrupt what they check.
        try:
            if firewall_blocks(port):
                print(fmt.warning(
                    f"  firewalld is blocking port {port}, so only the "
                    f"127.0.0.1 URL will work from this box."))
                print(fmt.dim(
                    f"    Reach it from another machine either by "
                    f"forwarding it over SSH (leaves the firewall alone):\n"
                    f"      ssh -L {port}:127.0.0.1:{port} root@<this-box>\n"
                    f"    or by opening the port yourself. Note that this "
                    f"session may include firewall tasks, so the simulator "
                    f"will not change firewalld for you."))
        except Exception:
            pass
    return panel


def close_panel(panel):
    """Stop a panel started by open_panel(), best-effort."""
    if panel:
        try:
            panel.stop()
        except Exception:
            pass


PAGE_HTML = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>RHCSA Mock Exam &mdash; Tasks</title>
<style>
  /* Dark is the default. The OS preference applies only while the viewer
     has not chosen explicitly; data-theme (set by the toggle, remembered in
     localStorage) always wins in both directions. */
  :root, :root[data-theme="dark"] {
    --bg:#0e1116; --sunk:#0a0d11; --panel:#161a21; --panel2:#1c212a;
    --edge:#252b35; --edge2:#333b47;
    --ink:#e8ebf0; --dim:#9aa4b2; --faint:#6b7280;
    --accent:#3b82f6; --done:#22c55e; --revisit:#f59e0b; --crit:#ef4444;
    --radius:14px;
  }
  @media (prefers-color-scheme: light) {
    :root:not([data-theme]) {
      --bg:#f5f6f8; --sunk:#eceef2; --panel:#fff; --panel2:#f8f9fb;
      --edge:#e2e5ea; --edge2:#cfd4dc;
      --ink:#11151b; --dim:#5b6472; --faint:#858d99;
      --done:#15803d; --revisit:#b45309;
    }
  }
  :root[data-theme="light"] {
    --bg:#f5f6f8; --sunk:#eceef2; --panel:#fff; --panel2:#f8f9fb;
    --edge:#e2e5ea; --edge2:#cfd4dc;
    --ink:#11151b; --dim:#5b6472; --faint:#858d99;
    --done:#15803d; --revisit:#b45309;
  }
  * { box-sizing:border-box; }
  html,body { height:100%; }
  body {
    margin:0; background:var(--bg); color:var(--ink);
    font:15px/1.55 system-ui, -apple-system, "Segoe UI", Cantarell, Roboto,
         "Helvetica Neue", Arial, sans-serif;
    -webkit-font-smoothing:antialiased;
  }
  #wrap { display:flex; min-height:100%; }

  /* ── sidebar ───────────────────────────────────────────────────────── */
  aside {
    width:248px; flex:0 0 248px; background:var(--sunk);
    border-right:1px solid var(--edge); padding:22px 18px;
    position:sticky; top:0; height:100vh;
    display:flex; flex-direction:column; gap:20px;
  }
  .brand { display:flex; align-items:center; gap:10px; }
  .glyph { width:30px; height:30px; border-radius:9px; flex:0 0 30px;
           background:linear-gradient(135deg,var(--accent),#8b5cf6); }
  .brand b { font-size:15px; font-weight:620; letter-spacing:-.1px; }
  .brand span { display:block; font-size:11.5px; color:var(--faint);
                font-weight:450; letter-spacing:.3px; }

  .clockwrap { background:var(--panel); border:1px solid var(--edge);
               border-radius:var(--radius); padding:14px 16px; }
  .clocklabel { font-size:11px; text-transform:uppercase; letter-spacing:.9px;
                color:var(--faint); margin-bottom:5px; }
  .clock { font-size:30px; font-weight:640; letter-spacing:-.5px;
           font-variant-numeric:tabular-nums; line-height:1.1; }
  .clock.warn { color:var(--revisit); }
  .clock.crit { color:var(--crit); }

  .prog { display:flex; flex-direction:column; gap:9px; }
  .progbar { height:6px; border-radius:99px; background:var(--edge); overflow:hidden; }
  .progbar i { display:block; height:100%; background:var(--done);
               border-radius:99px; transition:width .25s ease; }
  .stats { display:flex; gap:8px; }
  .stat { flex:1; background:var(--panel); border:1px solid var(--edge);
          border-radius:11px; padding:9px 10px; }
  .stat b { display:block; font-size:19px; font-weight:640;
            font-variant-numeric:tabular-nums; line-height:1.15; }
  .stat span { font-size:11px; color:var(--faint); }
  .stat.d b { color:var(--done); }
  .stat.r b { color:var(--revisit); }
  .side-foot { margin-top:auto; display:flex; flex-direction:column; gap:12px; }
  .side-note { font-size:11.5px; color:var(--faint); line-height:1.5; }
  #theme {
    font:inherit; font-size:12.5px; padding:8px 12px; border-radius:9px;
    border:1px solid var(--edge2); background:var(--panel); color:var(--dim);
    cursor:pointer; display:flex; align-items:center; gap:8px;
  }
  #theme:hover { color:var(--ink); border-color:var(--accent); }

  /* ── main ──────────────────────────────────────────────────────────── */
  main { flex:1; padding:26px 30px 60px; max-width:960px; }
  .topbar { display:flex; align-items:center; gap:12px; margin-bottom:16px;
            flex-wrap:wrap; }
  .hostchip {
    display:inline-flex; align-items:center; gap:8px;
    background:var(--panel); border:1px solid var(--edge);
    border-radius:99px; padding:6px 14px 6px 11px; font-size:13px; color:var(--dim);
  }
  .hostchip i { width:7px; height:7px; border-radius:99px; background:var(--done); }
  .hostchip code {
    font-family:ui-monospace,SFMono-Regular,"JetBrains Mono",Menlo,monospace;
    font-size:12.5px; color:var(--ink);
  }
  .spacer { margin-left:auto; }
  .ghost {
    font:inherit; font-size:13px; padding:7px 13px; border-radius:9px;
    border:1px solid var(--edge2); background:transparent; color:var(--dim);
    cursor:pointer;
  }
  .ghost:hover { color:var(--ink); border-color:var(--accent); }

  /* ── accordion ─────────────────────────────────────────────────────── */
  .item {
    background:var(--panel); border:1px solid var(--edge);
    border-radius:12px; margin-bottom:8px; overflow:hidden;
    transition:border-color .12s;
  }
  .item.sel { border-color:var(--accent); }
  .item.is-revisit { box-shadow:inset 3px 0 0 var(--revisit); }
  .item.is-done .label { color:var(--faint); }

  .row {
    display:flex; align-items:center; gap:13px; padding:13px 16px;
    cursor:pointer; user-select:none;
  }
  .row:hover { background:var(--panel2); }
  .chev {
    width:9px; height:9px; flex:0 0 9px; margin-right:1px;
    border-right:2px solid var(--faint); border-bottom:2px solid var(--faint);
    transform:rotate(-45deg); transition:transform .16s ease;
  }
  .item.open .chev { transform:rotate(45deg); }
  .label { font-size:15px; font-weight:540; font-variant-numeric:tabular-nums; }
  .cat {
    font-size:11.5px; color:var(--faint); background:var(--panel2);
    border:1px solid var(--edge); border-radius:99px; padding:2px 9px;
  }
  .rowpts { margin-left:auto; font-size:12.5px; color:var(--faint);
            font-variant-numeric:tabular-nums; }

  .marks { display:flex; gap:7px; }
  .mk {
    display:inline-flex; align-items:center; gap:7px; cursor:pointer;
    font-size:12.5px; padding:6px 11px; border-radius:9px;
    border:1px solid var(--edge2); background:var(--panel); color:var(--dim);
    transition:background .12s, border-color .12s, color .12s;
  }
  .mk:hover { color:var(--ink); }
  .mk .box {
    width:15px; height:15px; border-radius:5px; flex:0 0 15px;
    border:1.5px solid var(--edge2); display:grid; place-items:center;
    font-size:10px; line-height:1; color:transparent;
  }
  .mk.on { color:var(--ink); }
  .mk.on-done { border-color:var(--done); background:color-mix(in srgb,var(--done) 14%,transparent); }
  .mk.on-done .box { background:var(--done); border-color:var(--done); color:#fff; }
  .mk.on-revisit { border-color:var(--revisit); background:color-mix(in srgb,var(--revisit) 14%,transparent); }
  .mk.on-revisit .box { background:var(--revisit); border-color:var(--revisit); color:#fff; }

  .drawer {
    display:none; padding:4px 18px 18px 39px;
    border-top:1px solid var(--edge);
  }
  .item.open .drawer { display:block; }
  .desc { white-space:pre-wrap; font-size:15.5px; line-height:1.65; padding-top:14px; }
  .desc.mono {
    font-family:ui-monospace,SFMono-Regular,"JetBrains Mono",Menlo,monospace;
    font-size:13.8px; line-height:1.7;
  }
  .meta { margin-top:13px; font-size:12px; color:var(--faint); }

  .keys { margin-top:20px; font-size:12px; color:var(--faint); }
  kbd { font:inherit; font-size:11px; padding:1.5px 6px; border-radius:5px;
        background:var(--panel2); border:1px solid var(--edge2); color:var(--dim); }

  /* actions + results */
  .actions { display:flex; flex-direction:column; gap:8px; }
  .btn {
    font:inherit; font-size:13.5px; padding:10px 14px; border-radius:10px;
    border:1px solid var(--edge2); background:var(--panel); color:var(--ink);
    cursor:pointer; text-align:center; transition:background .12s,border-color .12s;
  }
  .btn:hover:not(:disabled) { border-color:var(--accent); background:var(--panel2); }
  .btn:disabled { opacity:.45; cursor:default; }
  .btn.primary { background:var(--accent); border-color:var(--accent); color:#fff; }
  .btn.primary:hover:not(:disabled) { filter:brightness(1.08); background:var(--accent); }
  .btn.danger { color:var(--crit); border-color:color-mix(in srgb,var(--crit) 45%,transparent); }
  .btn.danger:hover:not(:disabled) { background:color-mix(in srgb,var(--crit) 12%,transparent);
                                     border-color:var(--crit); }

  .banner {
    border-radius:12px; padding:13px 16px; margin-bottom:14px; font-size:14px;
    border:1px solid var(--edge); background:var(--panel);
  }
  .banner.ok { border-color:var(--done); background:color-mix(in srgb,var(--done) 12%,transparent); }
  .banner.bad { border-color:var(--crit); background:color-mix(in srgb,var(--crit) 12%,transparent); }
  .banner.busy { border-color:var(--accent); background:color-mix(in srgb,var(--accent) 12%,transparent); }
  .banner b { display:block; font-size:16px; margin-bottom:3px; }

  .scoreline { display:flex; align-items:baseline; gap:12px; margin-bottom:14px; }
  .scorebig { font-size:30px; font-weight:660; font-variant-numeric:tabular-nums; }
  .verdict { font-size:14px; font-weight:600; padding:3px 12px; border-radius:99px; }
  .verdict.pass { color:var(--done); background:color-mix(in srgb,var(--done) 15%,transparent); }
  .verdict.fail { color:var(--crit); background:color-mix(in srgb,var(--crit) 15%,transparent); }

  .check { display:flex; gap:10px; padding:7px 0; font-size:14px;
           border-top:1px solid var(--edge); }
  .check:first-child { border-top:0; }
  .check .mark { width:16px; flex:0 0 16px; font-weight:700; }
  .check.ok .mark { color:var(--done); }
  .check.no .mark { color:var(--crit); }
  .check .msg { flex:1; }
  .check .pts { color:var(--faint); font-variant-numeric:tabular-nums; font-size:12.5px; }

  /* dialog */
  .scrim { position:fixed; inset:0; background:rgba(0,0,0,.55); display:grid;
           place-items:center; padding:20px; z-index:20; }
  .dialog {
    background:var(--panel); border:1px solid var(--edge2); border-radius:14px;
    padding:22px 24px; max-width:620px; width:100%; max-height:86vh; overflow:auto;
  }
  .dialog h3 { margin:0 0 6px; font-size:17px; }
  .dialog p { color:var(--dim); font-size:13.5px; margin:0 0 14px; }
  .dialog label.row { display:flex; gap:9px; align-items:flex-start; padding:7px 0;
                      font-size:13.5px; cursor:pointer; }
  textarea {
    width:100%; min-height:110px; font:inherit; font-size:14px; padding:11px 13px;
    border-radius:10px; border:1px solid var(--edge2); background:var(--panel2);
    color:var(--ink); resize:vertical;
  }
  textarea:focus { outline:2px solid var(--accent); outline-offset:1px; }
  .dialog .foot { display:flex; gap:9px; justify-content:flex-end; margin-top:16px; }
  .note { font-size:12.5px; color:var(--faint); line-height:1.55; margin-top:10px; }
  .note code { font-family:ui-monospace,Menlo,monospace; font-size:11.5px; }

  .empty { padding:80px 0; text-align:center; color:var(--faint); }
  .empty b { display:block; font-size:16px; color:var(--dim); margin-bottom:6px;
             font-weight:550; }

  @media (max-width:760px) {
    #wrap { display:block; }
    aside { width:auto; height:auto; position:static; flex-direction:row;
            flex-wrap:wrap; align-items:center; border-right:0;
            border-bottom:1px solid var(--edge); }
    .clockwrap, .prog { flex:1; } .side-note { display:none; }
    main { padding:18px 14px 40px; }
    .rowpts, .cat { display:none; }
  }
</style>
</head>
<body>
<div id="wrap">
  <aside>
    <div class="brand">
      <div class="glyph"></div>
      <div><b>RHCSA Mock Exam</b><span>EX200 practice</span></div>
    </div>
    <div class="clockwrap">
      <div class="clocklabel">Time remaining</div>
      <div class="clock" id="clock">&mdash;</div>
    </div>
    <div class="prog">
      <div class="progbar"><i id="progfill" style="width:0%"></i></div>
      <div class="stats">
        <div class="stat d"><b id="ndone">0</b><span>done</span></div>
        <div class="stat r"><b id="nrev">0</b><span>revisit</span></div>
        <div class="stat"><b id="nleft">0</b><span>left</span></div>
      </div>
    </div>
    <div class="actions">
      <button class="btn primary" id="submit">Submit for grading</button>
      <button class="btn danger" id="resetlab">Reset lab environment</button>
    </div>

    <div class="side-foot">
      <div class="side-note">Ticks are your own notes — they do not affect
        grading. Submitting runs the real validators against this system.</div>
      <button id="theme"><span id="themeicon">&#9789;</span><span id="themetext">Dark</span></button>
    </div>
  </aside>

  <main>
    <div id="banner"></div>
    <div class="topbar" id="topbar"></div>
    <div id="results"></div>
    <div id="list">
      <div class="empty"><b>Waiting for an exam to start</b>
        Start one in the terminal &mdash; this panel follows it.</div>
    </div>
    <div class="keys" id="keys"></div>
  </main>
</div>
<div id="modal"></div>

<script>
(function () {
  var state = { tasks: [] };
  var open = {};             // task id -> drawer expanded
  var openResult = {};       // task id -> result drawer expanded
  var sel = 0;               // keyboard cursor, 0-based
  var localRemaining = null; // ticks locally between polls
  var busy = false;          // an action is in flight
  var flash = null;          // {kind, title, body} shown as a banner

  var $ = function (id) { return document.getElementById(id); };

  // The session token arrives in the URL the exam printed. Keep it out of
  // later requests' query strings by sending it as a header instead.
  var TOKEN = (new URLSearchParams(location.search)).get('t') || '';

  function api(path, opts) {
    opts = opts || {};
    opts.headers = Object.assign({'Content-Type': 'application/json'},
                                 opts.headers || {});
    if (TOKEN) opts.headers['X-Panel-Token'] = TOKEN;
    return fetch(path, opts).then(function (r) {
      return r.json().catch(function () { return {}; }).then(function (body) {
        if (!r.ok) throw new Error(body.error || ('HTTP ' + r.status));
        return body;
      });
    });
  }

  function setFlash(kind, title, body) {
    flash = { kind: kind, title: title, body: body || '' };
    render();
  }

  // ── theme ───────────────────────────────────────────────────────────
  // Follows the OS until the viewer picks one, then remembers the choice.
  var THEME_KEY = 'rhcsa-panel-theme';

  function systemTheme() {
    return (window.matchMedia
      && window.matchMedia('(prefers-color-scheme: light)').matches)
      ? 'light' : 'dark';
  }

  function currentTheme() {
    return document.documentElement.getAttribute('data-theme') || systemTheme();
  }

  function applyTheme(name) {
    if (name) document.documentElement.setAttribute('data-theme', name);
    var dark = currentTheme() === 'dark';
    $('themeicon').innerHTML = dark ? '&#9789;' : '&#9788;';   // moon / sun
    $('themetext').textContent = dark ? 'Dark' : 'Light';
  }

  try {
    var saved = localStorage.getItem(THEME_KEY);
    if (saved === 'light' || saved === 'dark') applyTheme(saved);
    else applyTheme(null);
  } catch (err) { applyTheme(null); }

  $('theme').addEventListener('click', function () {
    var next = currentTheme() === 'dark' ? 'light' : 'dark';
    applyTheme(next);
    try { localStorage.setItem(THEME_KEY, next); } catch (err) { /* private mode */ }
  });

  function esc(s) {
    return String(s === null || s === undefined ? '' : s)
      .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
  }

  function fmtClock(s) {
    if (s === null || s === undefined) return null;
    if (s < 0) s = 0;
    var h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60), x = Math.floor(s % 60);
    var p = function (n) { return (n < 10 ? '0' : '') + n; };
    return h + ':' + p(m) + ':' + p(x);
  }

  function renderClock() {
    var el = $('clock');
    var t = fmtClock(localRemaining);
    if (t === null) { el.textContent = 'No limit'; el.className = 'clock'; return; }
    el.textContent = t;
    el.className = 'clock' + (localRemaining <= 300 ? ' crit'
                            : localRemaining <= 900 ? ' warn' : '');
  }

  function renderBanner() {
    var el = $('banner');
    if (flash) {
      el.innerHTML = '<div class="banner ' + flash.kind + '"><b>'
        + esc(flash.title) + '</b>' + esc(flash.body) + '</div>';
      return;
    }
    if (state.status === 'validating') {
      el.innerHTML = '<div class="banner busy"><b>Validating…</b>'
        + 'Running the checks against this system. Watch the terminal for '
        + 'progress; results appear here when it finishes.</div>';
      return;
    }
    el.innerHTML = '';
  }

  function renderResults() {
    var el = $('results');
    var r = state.results;
    if (!r) { el.innerHTML = ''; return; }

    var head = ''
      + '<div class="scoreline">'
      +   '<span class="scorebig">' + r.score + ' / ' + r.max_score + '</span>'
      +   '<span class="verdict ' + (r.passed ? 'pass' : 'fail') + '">'
      +     (r.passed ? 'PASS' : 'FAIL') + ' \u00b7 ' + r.percentage + '%</span>'
      + '</div>'
      + '<div class="keys" style="margin:0 0 12px">Open a task to see every '
      +   'check and dispute a result you think is wrong.</div>';

    var rows = (r.tasks || []).map(function (t, i) {
      var isOpen = !!openResult[t.task_id];
      var checks = (t.checks || []).map(function (c) {
        return '<div class="check ' + (c.passed ? 'ok' : 'no') + '">'
          + '<span class="mark">' + (c.passed ? '\u2713' : '\u2717') + '</span>'
          + '<span class="msg">' + esc(c.message || c.name) + '</span>'
          + '<span class="pts">' + c.points + '/' + c.max_points + '</span>'
          + '</div>';
      }).join('');

      return ''
        + '<div class="item' + (isOpen ? ' open' : '') + '" data-r="' + i + '">'
        +   '<div class="row" data-act="rtoggle">'
        +     '<span class="chev"></span>'
        +     '<span class="label">Task ' + (i + 1 < 10 ? '0' : '') + (i + 1) + '</span>'
        +     '<span class="cat">' + esc(t.category) + '</span>'
        +     '<span class="rowpts">' + t.score + '/' + t.max_score + ' pts</span>'
        +     '<span class="verdict ' + (t.passed ? 'pass' : 'fail') + '">'
        +       (t.passed ? 'PASS' : 'FAIL') + '</span>'
        +   '</div>'
        +   '<div class="drawer">'
        +     '<div class="desc mono">' + esc(t.description) + '</div>'
        +     '<div style="margin-top:14px">' + checks + '</div>'
        +     '<div class="nav">'
        +       '<button class="btn" data-act="dispute" data-task="'
        +         esc(t.task_id) + '">Dispute this result</button>'
        +     '</div>'
        +   '</div>'
        + '</div>';
    }).join('');

    el.innerHTML = head + rows;
  }

  function render() {
    var ts = state.tasks || [];
    var done = state.done_count || 0;
    $('ndone').textContent = done;
    $('nrev').textContent = state.revisit_count || 0;
    $('nleft').textContent = Math.max(0, ts.length - done);
    $('progfill').style.width = ts.length ? (done / ts.length * 100) + '%' : '0%';

    renderBanner();
    renderResults();

    var graded = state.status === 'complete';
    var sb = $('submit');
    if (sb) {
      sb.disabled = busy || graded || state.status === 'validating' || !ts.length
                    || !state.can_control;
      sb.textContent = graded ? 'Graded' :
        (state.status === 'validating' ? 'Validating\u2026' : 'Submit for grading');
    }
    var rb = $('resetlab');
    if (rb) rb.disabled = busy || !state.can_control;

    if (graded) {
      // Results carry the task text and are numbered the same way, so
      // keeping the question sheet below them just showed everything twice.
      $('topbar').innerHTML = '';
      $('keys').innerHTML = '';
      $('list').innerHTML = '';
      return;
    }

    if (!ts.length) {
      $('topbar').innerHTML = '';
      $('keys').innerHTML = '';
      $('list').innerHTML = '<div class="empty"><b>Waiting for an exam to start</b>'
        + 'Start one in the terminal &mdash; this panel follows it.</div>';
      return;
    }
    if (sel >= ts.length) sel = ts.length - 1;

    var anyOpen = ts.some(function (t) { return open[t.id]; });
    $('topbar').innerHTML =
      '<div class="hostchip"><i></i>Perform these tasks on <code>'
      + esc(ts[0].host) + '</code></div>'
      + '<span class="spacer"></span>'
      + '<button class="ghost" id="toggleall">'
      + (anyOpen ? 'Collapse all' : 'Expand all') + '</button>';

    $('keys').innerHTML = '<kbd>j</kbd><kbd>k</kbd> move &nbsp; '
      + '<kbd>enter</kbd> open &nbsp; <kbd>d</kbd> done &nbsp; <kbd>r</kbd> revisit';

    // Labels stay deliberately generic, as on the real sheet: you cannot
    // triage the list by reading it, you have to open each one.
    $('list').innerHTML = ts.map(function (t, i) {
      var isOpen = !!open[t.id];
      var cls = 'item' + (isOpen ? ' open' : '') + (i === sel ? ' sel' : '')
        + (t.done ? ' is-done' : '') + (t.revisit ? ' is-revisit' : '');
      var mono = t.description.indexOf('\\n') !== -1 ? ' mono' : '';
      var dom = t.domain_name ? ('Domain ' + t.domain + ' \\u00b7 ' + t.domain_name) : '';
      return ''
        + '<div class="' + cls + '" data-i="' + i + '">'
        +   '<div class="row" data-act="toggle">'
        +     '<span class="chev"></span>'
        +     '<span class="label">Task ' + (t.n < 10 ? '0' : '') + t.n + '</span>'
        +     (isOpen ? '<span class="cat">' + esc(t.category) + '</span>' : '')
        +     '<span class="rowpts">' + t.points + ' pts</span>'
        +     '<span class="marks">'
        +       mk(t, 'revisit', 'Revisit') + mk(t, 'done', 'Done')
        +     '</span>'
        +   '</div>'
        +   '<div class="drawer">'
        +     '<div class="desc' + mono + '">' + esc(t.description) + '</div>'
        +     (dom ? '<div class="meta">' + esc(dom) + '</div>' : '')
        +   '</div>'
        + '</div>';
    }).join('');
  }

  function mk(t, field, label) {
    var on = !!t[field];
    return '<label class="mk' + (on ? ' on on-' + field : '') + '" data-act="mark"'
      + ' data-field="' + field + '"><span class="box">\\u2713</span>'
      + label + '</label>';
  }

  function mark(i, field, value) {
    var ts = state.tasks || [];
    var t = ts[i];
    if (!t) return;
    t[field] = value;                      // optimistic; poll reconciles
    state.done_count = ts.filter(function (x) { return x.done; }).length;
    state.revisit_count = ts.filter(function (x) { return x.revisit; }).length;
    render();
    api('/api/mark', {
      method: 'POST',
      body: JSON.stringify({ id: t.id, field: field, value: value })
    }).catch(function () { /* marks are advisory; ignore */ });
  }

  function toggle(i) {
    var t = (state.tasks || [])[i];
    if (!t) return;
    open[t.id] = !open[t.id];
    render();
  }

  function move(delta) {
    var ts = state.tasks || [];
    if (!ts.length) return;
    sel = Math.max(0, Math.min(ts.length - 1, sel + delta));
    render();
    var el = document.querySelector('.item.sel');
    if (el) el.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
  }

  // ── actions ─────────────────────────────────────────────────────────

  function submitForGrading() {
    if (busy) return;
    if (!confirm('Submit for grading?\\n\\nThe validators will run against '
                 + 'this system now. You cannot un-submit.')) return;
    busy = true;
    render();
    api('/api/validate', { method: 'POST' })
      .then(function (res) {
        state.status = res.status || 'validating';
        setFlash('busy', 'Submitted',
                 'Grading is running on the exam host. Results appear here '
                 + 'when it finishes.');
      })
      .catch(function (e) { setFlash('bad', 'Could not submit', e.message); })
      .then(function () { busy = false; render(); });
  }

  function resetLab() {
    if (busy) return;
    if (!confirm('Reset the lab environment?\\n\\nThis clears practice mounts, '
                 + 'loop devices and leftover task artifacts. It is refused '
                 + 'while an exam is in progress.')) return;
    busy = true;
    render();
    api('/api/reset-lab', { method: 'POST',
                            body: JSON.stringify({ confirm: true }) })
      .then(function (res) {
        if (res.ok) setFlash('ok', 'Lab reset', res.message || '');
        else setFlash('bad', 'Reset refused', res.error || '');
      })
      .catch(function (e) { setFlash('bad', 'Reset failed', e.message); })
      .then(function () { busy = false; render(); });
  }

  function closeModal() { $('modal').innerHTML = ''; }

  function openDispute(taskId) {
    var r = state.results || {};
    var task = (r.tasks || []).filter(function (t) {
      return t.task_id === taskId; })[0];
    if (!task) return;

    var rows = (task.checks || []).map(function (c, i) {
      return '<label class="row"><input type="checkbox" data-check="'
        + esc(c.name) + '"' + (c.passed ? '' : ' checked') + '>'
        + '<span>' + (c.passed ? '\u2713' : '\u2717') + ' '
        + esc(c.message || c.name) + '</span></label>';
    }).join('');

    $('modal').innerHTML = ''
      + '<div class="scrim" data-act="scrim"><div class="dialog">'
      +   '<h3>Dispute a checker result</h3>'
      +   '<p>' + esc(task.task_id) + ' \u00b7 scored ' + task.score + '/'
      +     task.max_score + '. Tick the checks you believe are wrong.</p>'
      +   rows
      +   '<p style="margin:14px 0 6px">Why is the checker wrong? Be specific '
      +     '\u2014 the reviewer reads this against the captured evidence.</p>'
      +   '<textarea id="disputearg" placeholder="e.g. The check greps for '
      +     'ext4 but the task asked for xfs, so a correct answer fails."></textarea>'
      +   '<label class="row" style="margin-top:10px">'
      +     '<input type="checkbox" id="disputesubmit" checked>'
      +     '<span>Open a GitHub issue as well as saving locally</span></label>'
      +   '<div class="note">The report is written to <code>data/disputes/</code> '
      +     'first, so the evidence survives even if submitting fails. If an '
      +     'issue is opened, the AI reviewer posts its verdict as a comment '
      +     'there \u2014 it does not come back into this panel.</div>'
      +   '<div class="foot">'
      +     '<button class="btn" data-act="cancel">Cancel</button>'
      +     '<button class="btn primary" data-act="filedispute" data-task="'
      +       esc(taskId) + '">File dispute</button>'
      +   '</div>'
      + '</div></div>';
  }

  function fileDispute(taskId) {
    var boxes = document.querySelectorAll('[data-check]');
    var checks = [];
    for (var i = 0; i < boxes.length; i++) {
      if (boxes[i].checked) checks.push(boxes[i].getAttribute('data-check'));
    }
    var argument = ($('disputearg') || {}).value || '';
    var submit = ($('disputesubmit') || {}).checked;

    if (!checks.length) { alert('Tick at least one check to dispute.'); return; }
    if (!argument.trim()) { alert('Explain why the checker is wrong.'); return; }

    busy = true;
    closeModal();
    render();
    api('/api/dispute', {
      method: 'POST',
      body: JSON.stringify({ task_id: taskId, checks: checks,
                             argument: argument, submit: submit })
    }).then(function (res) {
      if (!res.ok) { setFlash('bad', 'Dispute not filed', res.error || ''); return; }
      var body = 'Saved to ' + res.saved_to + '. ' + (res.message || '');
      if (res.issue_url) body += ' ' + res.issue_url;
      setFlash(res.submitted ? 'ok' : 'busy', 'Dispute filed', body);
    }).catch(function (e) {
      setFlash('bad', 'Dispute failed', e.message);
    }).then(function () { busy = false; render(); });
  }

  function poll() {
    api('/api/state').then(function (s) {
      state = s;
      if (typeof s.remaining_seconds === 'number') localRemaining = s.remaining_seconds;
      else if (s.remaining_seconds === null) localRemaining = null;
      render();
      renderClock();
    }).catch(function () { /* terminal session ended; keep last view */ });
  }

  document.addEventListener('click', function (e) {
    if (e.target.id === 'submit') { submitForGrading(); return; }
    if (e.target.id === 'resetlab') { resetLab(); return; }

    var act = e.target.getAttribute && e.target.getAttribute('data-act');
    if (act === 'cancel' || act === 'scrim') {
      if (act === 'scrim' && e.target !== e.currentTarget
          && !e.target.classList.contains('scrim')) return;
      closeModal();
      return;
    }
    if (act === 'filedispute') {
      fileDispute(e.target.getAttribute('data-task'));
      return;
    }
    if (act === 'dispute') {
      openDispute(e.target.getAttribute('data-task'));
      return;
    }

    var rhost = e.target.closest('[data-r]');
    if (rhost && e.target.closest('[data-act="rtoggle"]')) {
      var ri = parseInt(rhost.getAttribute('data-r'), 10);
      var rt = ((state.results || {}).tasks || [])[ri];
      if (rt) { openResult[rt.task_id] = !openResult[rt.task_id]; render(); }
      return;
    }

    if (e.target.id === 'toggleall') {
      var ts = state.tasks || [];
      var anyOpen = ts.some(function (t) { return open[t.id]; });
      ts.forEach(function (t) { open[t.id] = !anyOpen; });
      render();
      return;
    }
    var host = e.target.closest('[data-i]');
    if (!host) return;
    var i = parseInt(host.getAttribute('data-i'), 10);
    sel = i;
    var lbl = e.target.closest('[data-act="mark"]');
    if (lbl) {
      // Each toggles independently — click again to clear, and a task can
      // be both done and flagged for another look.
      var t = (state.tasks || [])[i];
      if (t) mark(i, lbl.getAttribute('data-field'), !t[lbl.getAttribute('data-field')]);
      e.preventDefault();
      return;
    }
    if (e.target.closest('[data-act="toggle"]')) toggle(i);
  });

  document.addEventListener('keydown', function (e) {
    if (e.key === 'Escape') { closeModal(); return; }
    // Never steal keys while the candidate is typing their dispute.
    if (e.target && (e.target.tagName === 'TEXTAREA'
                     || e.target.tagName === 'INPUT')) return;
    if (e.metaKey || e.ctrlKey || e.altKey) return;
    var t = (state.tasks || [])[sel];
    var k = e.key;
    if (k === 'j' || k === 'ArrowDown') { move(1); e.preventDefault(); }
    else if (k === 'k' || k === 'ArrowUp') { move(-1); e.preventDefault(); }
    else if (k === 'Enter' || k === ' ') { toggle(sel); e.preventDefault(); }
    else if (k === 'd' && t) { mark(sel, 'done', !t.done); e.preventDefault(); }
    else if (k === 'r' && t) { mark(sel, 'revisit', !t.revisit); e.preventDefault(); }
  });

  // The clock ticks locally so it stays smooth between polls; the poll is
  // authoritative, since it is anchored to uptime and survives a reboot.
  setInterval(function () {
    if (typeof localRemaining === 'number' && localRemaining > 0) {
      localRemaining -= 1;
      renderClock();
    }
  }, 1000);

  setInterval(poll, 3000);
  poll();
})();
</script>
</body>
</html>
"""
