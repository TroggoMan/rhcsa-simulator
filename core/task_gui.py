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
- Read-mostly. The panel shows state and records ticks; it never validates,
  never mutates the system, and never touches task state the grader reads.
- Marks live server-side so the view survives a page reload and is shared
  across windows (laptop and phone show the same ticks).
- The page holds no state worth losing: it polls /api/state and re-renders.
- Runs on a daemon thread. A dead or hung panel must never hold up an exam,
  so every failure path degrades to "no panel" rather than raising.
"""

import json
import logging
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

    def do_GET(self):
        path = self.path.split('?', 1)[0].rstrip('/') or '/'
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
        else:
            self._send(404, '{"error":"not found"}', 'application/json')

    def do_POST(self):
        path = self.path.split('?', 1)[0].rstrip('/') or '/'
        if path != '/api/mark':
            self._send(404, '{"error":"not found"}', 'application/json')
            return
        try:
            length = int(self.headers.get('Content-Length') or 0)
            payload = json.loads(self.rfile.read(length) or b'{}')
            task_id = payload.get('id')
            field = payload.get('field')
            value = bool(payload.get('value'))
        except (ValueError, TypeError, OSError):
            self._send(400, '{"error":"bad request"}', 'application/json')
            return
        try:
            state = set_mark(task_id, field, value)
        except ValueError:
            self._send(400, '{"error":"unknown mark"}', 'application/json')
            return
        self._send(200, json.dumps({'id': task_id, 'marks': state}),
                   'application/json')


class TaskPanel:
    """Background HTTP server showing the current exam's task sheet."""

    def __init__(self, state_provider, port=DEFAULT_PORT, bind='0.0.0.0'):
        self.state_provider = state_provider
        self.port = port
        self.bind = bind
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
        httpd.daemon_threads = True
        self._httpd = httpd
        self._thread = threading.Thread(target=httpd.serve_forever,
                                        name='rhcsa-task-panel', daemon=True)
        self._thread.start()
        return self.urls()

    def urls(self):
        if not self.running:
            return []
        port = self._httpd.server_address[1]
        if self.bind in ('127.0.0.1', 'localhost'):
            return ['http://127.0.0.1:%d/' % port]
        return _local_addresses(port)

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


def start_for_session(session, port=DEFAULT_PORT, bind='0.0.0.0'):
    """Start a panel backed by a live ExamSession. Never raises."""
    def provider():
        remaining = None
        try:
            from core import exam_clock
            remaining = exam_clock.remaining_seconds()
        except Exception:
            pass
        return build_state(getattr(session, 'tasks', []), remaining)

    try:
        panel = TaskPanel(provider, port=port, bind=bind)
        urls = panel.start()
        return (panel, urls) if urls else (None, [])
    except Exception as e:
        logger.warning("task panel failed to start: %s", e)
        return (None, [])


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
    <div class="side-foot">
      <div class="side-note">Ticks here are your own notes. Grading runs
        against real system state when you return to the terminal.</div>
      <button id="theme"><span id="themeicon">&#9789;</span><span id="themetext">Dark</span></button>
    </div>
  </aside>

  <main>
    <div class="topbar" id="topbar"></div>
    <div id="list">
      <div class="empty"><b>Waiting for an exam to start</b>
        Start one in the terminal &mdash; this panel follows it.</div>
    </div>
    <div class="keys" id="keys"></div>
  </main>
</div>

<script>
(function () {
  var state = { tasks: [] };
  var open = {};             // task id -> drawer expanded
  var sel = 0;               // keyboard cursor, 0-based
  var localRemaining = null; // ticks locally between polls

  var $ = function (id) { return document.getElementById(id); };

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

  function render() {
    var ts = state.tasks || [];
    var done = state.done_count || 0;
    $('ndone').textContent = done;
    $('nrev').textContent = state.revisit_count || 0;
    $('nleft').textContent = Math.max(0, ts.length - done);
    $('progfill').style.width = ts.length ? (done / ts.length * 100) + '%' : '0%';

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
    fetch('/api/mark', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ id: t.id, field: field, value: value })
    }).catch(function () { /* panel is advisory; ignore */ });
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

  function poll() {
    fetch('/api/state').then(function (r) { return r.json(); }).then(function (s) {
      state = s;
      if (typeof s.remaining_seconds === 'number') localRemaining = s.remaining_seconds;
      else if (s.remaining_seconds === null) localRemaining = null;
      render();
      renderClock();
    }).catch(function () { /* terminal session ended; keep last view */ });
  }

  document.addEventListener('click', function (e) {
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
