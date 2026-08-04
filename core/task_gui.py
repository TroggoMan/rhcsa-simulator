"""
Exam task panel — the question sheet as a separate window you manage.

WHY
---
On the real EX200 the tasks live in a window on the exam desktop, not in
your terminal: a checklist you tick off, with each task's detail hidden
until you open it. You read one, alt-tab away, work, alt-tab back, lose
your place, scroll, and repeat that twenty times under a clock. Candidates
consistently report that juggling that panel is its own skill, separate
from knowing the material — so practising against a scrollable pager in
the same terminal you're working in trains the wrong thing.

This serves the live task sheet over HTTP so it can sit in a browser window
beside your terminals, the way it will on the day.

SHAPE
-----
Same interaction model as the current exam, in a modern skin: a sidebar
carrying the countdown and a done/revisit tally, a "perform this task on
<host>" chip, and a **dropdown** that selects one task at a time. Entries
in that dropdown are deliberately generic ("Task 07") — exactly as on the
day, you cannot triage the list by reading it, you have to open each one.

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


def _local_addresses(port):
    """URLs the panel is reachable on, best-effort. The LAN address matters:
    the exam VM is usually headless, so the browser is on another machine."""
    urls = ['http://127.0.0.1:%d/' % port]
    try:
        # No traffic is sent — this just asks the kernel which source address
        # it would use, which is the one another host can reach us on.
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            s.connect(('192.0.2.1', 9))  # TEST-NET-1, guaranteed unroutable
            ip = s.getsockname()[0]
        finally:
            s.close()
        if ip and not ip.startswith('127.'):
            urls.append('http://%s:%d/' % (ip, port))
    except OSError:
        pass
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
  :root {
    --bg:#0e1116; --sunk:#0a0d11; --panel:#161a21; --panel2:#1c212a;
    --edge:#252b35; --edge2:#333b47;
    --ink:#e8ebf0; --dim:#9aa4b2; --faint:#6b7280;
    --accent:#3b82f6; --accent-ink:#fff;
    --done:#22c55e; --revisit:#f59e0b; --crit:#ef4444;
    --radius:14px;
  }
  @media (prefers-color-scheme: light) {
    :root {
      --bg:#f5f6f8; --sunk:#eceef2; --panel:#fff; --panel2:#f8f9fb;
      --edge:#e2e5ea; --edge2:#cfd4dc;
      --ink:#11151b; --dim:#5b6472; --faint:#858d99;
      --done:#15803d; --revisit:#b45309;
    }
  }
  * { box-sizing:border-box; }
  html,body { height:100%; }
  body {
    margin:0; background:var(--bg); color:var(--ink);
    font:15px/1.55 system-ui, -apple-system, "Segoe UI", Cantarell, Roboto,
         "Helvetica Neue", Arial, sans-serif;
    -webkit-font-smoothing:antialiased;
  }
  #wrap { display:flex; min-height:100%; gap:0; }

  /* ── sidebar ───────────────────────────────────────────────────────── */
  aside {
    width:248px; flex:0 0 248px; background:var(--sunk);
    border-right:1px solid var(--edge);
    padding:22px 18px; position:sticky; top:0; height:100vh;
    display:flex; flex-direction:column; gap:20px;
  }
  .brand { display:flex; align-items:center; gap:10px; }
  .glyph {
    width:30px; height:30px; border-radius:9px; flex:0 0 30px;
    background:linear-gradient(135deg,var(--accent),#8b5cf6);
  }
  .brand b { font-size:15px; font-weight:620; letter-spacing:-.1px; }
  .brand span { display:block; font-size:11.5px; color:var(--faint);
                font-weight:450; letter-spacing:.3px; }

  .clockwrap {
    background:var(--panel); border:1px solid var(--edge);
    border-radius:var(--radius); padding:14px 16px;
  }
  .clocklabel { font-size:11px; text-transform:uppercase; letter-spacing:.9px;
                color:var(--faint); margin-bottom:5px; }
  .clock {
    font-size:30px; font-weight:640; letter-spacing:-.5px;
    font-variant-numeric:tabular-nums; line-height:1.1;
  }
  .clock.warn { color:var(--revisit); }
  .clock.crit { color:var(--crit); }

  .prog { display:flex; flex-direction:column; gap:9px; }
  .progbar { height:6px; border-radius:99px; background:var(--edge); overflow:hidden; }
  .progbar i { display:block; height:100%; background:var(--done);
               border-radius:99px; transition:width .25s ease; }
  .stats { display:flex; gap:8px; }
  .stat {
    flex:1; background:var(--panel); border:1px solid var(--edge);
    border-radius:11px; padding:9px 10px;
  }
  .stat b { display:block; font-size:19px; font-weight:640;
            font-variant-numeric:tabular-nums; line-height:1.15; }
  .stat span { font-size:11px; color:var(--faint); letter-spacing:.2px; }
  .stat.d b { color:var(--done); }
  .stat.r b { color:var(--revisit); }

  .side-note { margin-top:auto; font-size:11.5px; color:var(--faint); line-height:1.5; }

  /* ── main ──────────────────────────────────────────────────────────── */
  main { flex:1; padding:26px 30px 50px; max-width:940px; }

  .hostchip {
    display:inline-flex; align-items:center; gap:8px; margin-bottom:18px;
    background:var(--panel); border:1px solid var(--edge);
    border-radius:99px; padding:6px 14px 6px 11px; font-size:13px; color:var(--dim);
  }
  .hostchip i {
    width:7px; height:7px; border-radius:99px; background:var(--done);
    box-shadow:0 0 0 3px color-mix(in srgb, var(--done) 22%, transparent);
  }
  .hostchip code {
    font-family:ui-monospace,SFMono-Regular,"JetBrains Mono",Menlo,monospace;
    font-size:12.5px; color:var(--ink);
  }

  .toolbar { display:flex; gap:12px; align-items:center; margin-bottom:16px;
             flex-wrap:wrap; }
  .selwrap { position:relative; flex:1; min-width:260px; max-width:520px; }
  select {
    appearance:none; width:100%; font:inherit; font-size:14.5px;
    padding:11px 38px 11px 14px; color:var(--ink);
    background:var(--panel); border:1px solid var(--edge2);
    border-radius:11px; cursor:pointer;
  }
  select:focus { outline:2px solid var(--accent); outline-offset:1px; }
  .selwrap::after {
    content:""; position:absolute; right:15px; top:50%; pointer-events:none;
    width:8px; height:8px; margin-top:-6px; border-right:2px solid var(--dim);
    border-bottom:2px solid var(--dim); transform:rotate(45deg);
  }

  .marks { display:flex; gap:8px; }
  .mk {
    display:inline-flex; align-items:center; gap:8px; cursor:pointer;
    user-select:none; font-size:14px; padding:10px 15px; border-radius:11px;
    border:1px solid var(--edge2); background:var(--panel); color:var(--dim);
    transition:background .12s, border-color .12s, color .12s;
  }
  .mk:hover { border-color:var(--edge2); color:var(--ink); }
  .mk .box {
    width:17px; height:17px; border-radius:6px; flex:0 0 17px;
    border:1.5px solid var(--edge2); display:grid; place-items:center;
    font-size:11px; line-height:1; color:transparent;
  }
  .mk.on { color:var(--ink); }
  .mk.on-done { border-color:var(--done); background:color-mix(in srgb,var(--done) 13%,transparent); }
  .mk.on-done .box { background:var(--done); border-color:var(--done); color:#fff; }
  .mk.on-revisit { border-color:var(--revisit); background:color-mix(in srgb,var(--revisit) 13%,transparent); }
  .mk.on-revisit .box { background:var(--revisit); border-color:var(--revisit); color:#fff; }

  .card {
    background:var(--panel); border:1px solid var(--edge);
    border-radius:var(--radius); padding:24px 26px;
  }
  .card-top {
    display:flex; align-items:center; gap:10px; margin-bottom:16px;
    padding-bottom:14px; border-bottom:1px solid var(--edge);
  }
  .tasknum { font-size:13px; color:var(--faint); font-variant-numeric:tabular-nums; }
  .pill {
    font-size:11.5px; letter-spacing:.3px; color:var(--dim);
    background:var(--panel2); border:1px solid var(--edge);
    border-radius:99px; padding:3px 10px;
  }
  .pts { margin-left:auto; font-size:13px; color:var(--faint);
         font-variant-numeric:tabular-nums; }
  .desc { white-space:pre-wrap; font-size:16px; line-height:1.65; }
  .desc.mono {
    font-family:ui-monospace,SFMono-Regular,"JetBrains Mono",Menlo,monospace;
    font-size:14px; line-height:1.7;
  }

  .nav { display:flex; gap:9px; align-items:center; margin-top:18px; }
  button {
    font:inherit; font-size:14px; padding:9px 16px; border-radius:10px;
    border:1px solid var(--edge2); background:var(--panel); color:var(--ink);
    cursor:pointer; transition:background .12s, border-color .12s;
  }
  button:hover:not(:disabled) { background:var(--panel2); border-color:var(--accent); }
  button:disabled { opacity:.4; cursor:default; }
  .keys { margin-left:auto; font-size:12px; color:var(--faint); }
  kbd {
    font:inherit; font-size:11px; padding:1.5px 6px; border-radius:5px;
    background:var(--panel2); border:1px solid var(--edge2); color:var(--dim);
  }

  .empty { padding:80px 0; text-align:center; color:var(--faint); }
  .empty b { display:block; font-size:16px; color:var(--dim); margin-bottom:6px;
             font-weight:550; }

  @media (max-width:760px) {
    #wrap { display:block; }
    aside { width:auto; height:auto; position:static; flex-direction:row;
            flex-wrap:wrap; align-items:center; border-right:0;
            border-bottom:1px solid var(--edge); }
    .clockwrap { flex:1; } .prog { flex:1; } .side-note { display:none; }
    main { padding:20px 16px 40px; }
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

    <div class="side-note">Ticks here are your own notes. Grading runs
      against real system state when you return to the terminal.</div>
  </aside>

  <main>
    <div id="sheet">
      <div class="empty"><b>Waiting for an exam to start</b>
        Start one in the terminal &mdash; this panel follows it.</div>
    </div>
  </main>
</div>

<script>
(function () {
  var state = { tasks: [] };
  var cur = 0;               // 0-based index of the selected task
  var localRemaining = null; // ticks locally between polls

  var $ = function (id) { return document.getElementById(id); };

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

  function renderSidebar() {
    var ts = state.tasks || [];
    var done = state.done_count || 0;
    $('ndone').textContent = done;
    $('nrev').textContent = state.revisit_count || 0;
    $('nleft').textContent = Math.max(0, ts.length - done);
    $('progfill').style.width = ts.length ? (done / ts.length * 100) + '%' : '0%';
  }

  function render() {
    var ts = state.tasks || [];
    renderSidebar();
    if (!ts.length) {
      $('sheet').innerHTML = '<div class="empty"><b>Waiting for an exam to start</b>'
        + 'Start one in the terminal &mdash; this panel follows it.</div>';
      return;
    }
    if (cur >= ts.length) cur = ts.length - 1;
    var t = ts[cur];

    // Entries stay deliberately generic, as on the real sheet: you cannot
    // triage the list by reading it, you have to open each one.
    var opts = ts.map(function (x, i) {
      var mark = x.done ? '\\u2713 ' : (x.revisit ? '\\u21ba ' : '');
      return '<option value="' + i + '"' + (i === cur ? ' selected' : '') + '>'
        + mark + 'Task ' + (x.n < 10 ? '0' : '') + x.n + '</option>';
    }).join('');

    var mono = t.description.indexOf('\\n') !== -1 ? ' mono' : '';
    var dom = t.domain_name ? ('Domain ' + t.domain + ' \\u00b7 ' + t.domain_name) : '';

    $('sheet').innerHTML = ''
      + '<div class="hostchip"><i></i>Perform this task on '
      +   '<code>' + esc(t.host) + '</code></div>'
      + '<div class="toolbar">'
      +   '<div class="selwrap"><select id="pick">' + opts + '</select></div>'
      +   '<div class="marks">' + mk(t, 'revisit', 'Revisit') + mk(t, 'done', 'Done') + '</div>'
      + '</div>'
      + '<div class="card">'
      +   '<div class="card-top">'
      +     '<span class="tasknum">Task ' + t.n + ' of ' + ts.length + '</span>'
      +     (dom ? '<span class="pill">' + esc(dom) + '</span>' : '')
      +     '<span class="pill">' + esc(t.category) + '</span>'
      +     '<span class="pts">' + t.points + ' points</span>'
      +   '</div>'
      +   '<div class="desc' + mono + '">' + esc(t.description) + '</div>'
      +   '<div class="nav">'
      +     '<button id="prev"' + (cur === 0 ? ' disabled' : '') + '>&larr; Previous</button>'
      +     '<button id="next"' + (cur === ts.length - 1 ? ' disabled' : '') + '>Next &rarr;</button>'
      +     '<span class="keys"><kbd>j</kbd><kbd>k</kbd> move &nbsp; '
      +       '<kbd>d</kbd> done &nbsp; <kbd>r</kbd> revisit</span>'
      +   '</div>'
      + '</div>';
  }

  function mk(t, field, label) {
    var on = !!t[field];
    return '<label class="mk' + (on ? ' on on-' + field : '') + '" data-field="'
      + field + '"><span class="box">\\u2713</span>' + label + '</label>';
  }

  function mark(field, value) {
    var ts = state.tasks || [];
    var t = ts[cur];
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

  function go(i) {
    var ts = state.tasks || [];
    if (!ts.length) return;
    cur = Math.max(0, Math.min(ts.length - 1, i));
    render();
  }

  function poll() {
    fetch('/api/state').then(function (r) { return r.json(); }).then(function (s) {
      var wasEmpty = !(state.tasks || []).length;
      state = s;
      if (typeof s.remaining_seconds === 'number') localRemaining = s.remaining_seconds;
      else if (s.remaining_seconds === null) localRemaining = null;
      if (wasEmpty && (s.tasks || []).length) cur = 0;
      render();
      renderClock();
    }).catch(function () { /* terminal session ended; keep last view */ });
  }

  document.addEventListener('change', function (e) {
    if (e.target.id === 'pick') go(parseInt(e.target.value, 10));
  });

  document.addEventListener('click', function (e) {
    if (e.target.id === 'prev') { go(cur - 1); return; }
    if (e.target.id === 'next') { go(cur + 1); return; }
    var lbl = e.target.closest('.mk');
    if (lbl) {
      // Each toggles independently — click again to clear, and a task can
      // be both done and flagged for another look.
      var t = (state.tasks || [])[cur];
      var field = lbl.getAttribute('data-field');
      if (t) mark(field, !t[field]);
      e.preventDefault();
    }
  });

  document.addEventListener('keydown', function (e) {
    if (e.metaKey || e.ctrlKey || e.altKey) return;
    if (e.target && e.target.tagName === 'SELECT') return;
    var t = (state.tasks || [])[cur];
    var k = e.key;
    if (k === 'j' || k === 'ArrowRight' || k === 'ArrowDown') { go(cur + 1); e.preventDefault(); }
    else if (k === 'k' || k === 'ArrowLeft' || k === 'ArrowUp') { go(cur - 1); e.preventDefault(); }
    else if (k === 'd' && t) { mark('done', !t.done); e.preventDefault(); }
    else if (k === 'r' && t) { mark('revisit', !t.revisit); e.preventDefault(); }
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
