"""
Tests for core.task_gui — the browser task panel.

The panel mirrors how the real EX200 presents its questions: a collapsed
checklist you tick "done" / "revisit" against, with each task's text hidden
until you open it. It is advisory only — ticking a box must never influence
grading, which still runs against real system state.
"""

import json
import urllib.error
import urllib.request

import pytest

from core import task_gui


class FakeTask:
    def __init__(self, id, description, category='lvm', points=10, domain=4):
        self.id = id
        self.description = description
        self.category = category
        self.points = points
        self.exam_domain = domain


@pytest.fixture(autouse=True)
def _clear_marks():
    task_gui.clear_marks()
    yield
    task_gui.clear_marks()


@pytest.fixture
def tasks():
    return [
        FakeTask('lvm_001', 'Create a 1GiB logical volume named lv_data.'),
        FakeTask('part_002', 'Create a 500MiB partition on /dev/sdb.',
                 category='partitioning', points=15, domain=4),
        FakeTask('sel_003', 'Set the SELinux context on /srv/web.',
                 category='selinux', points=20, domain=7),
    ]


TOKEN = 'test-token-abc123'


class FakeController:
    """Records what the panel asked for, without doing any of it."""

    def __init__(self):
        self.calls = []
        self.reset_allowed = True

    def request_validate(self):
        self.calls.append(('request_validate',))
        return {'queued': True, 'status': 'validating'}

    def file_dispute(self, task_id, check_names, argument, submit=True):
        self.calls.append(('file_dispute', task_id, tuple(check_names),
                           argument, submit))
        return {'saved_to': f'/var/lib/disputes/{task_id}.md',
                'submitted': submit, 'issue_url': 'https://example/issues/1'}

    def reset_lab(self, confirm=False):
        self.calls.append(('reset_lab', confirm))
        if not confirm:
            return {'ok': False, 'error': 'confirmation required'}
        return {'ok': True, 'message': 'lab reset'}

    def list_disputes(self):
        self.calls.append(('list_disputes',))
        return {'disputes': []}


@pytest.fixture
def controller():
    return FakeController()


@pytest.fixture
def panel(tasks, controller):
    """A live panel on an ephemeral loopback port, with auth enabled."""
    p = task_gui.TaskPanel(lambda: task_gui.build_state(tasks, 3600),
                           controller=controller, port=0, bind='127.0.0.1',
                           token=TOKEN)
    urls = p.start()
    assert urls, "panel failed to bind"
    base = urls[0].split('?')[0].rstrip('/')
    yield p, base
    p.stop()


def _get(base, path, token=TOKEN):
    headers = {'X-Panel-Token': token} if token is not None else {}
    req = urllib.request.Request(base + path, headers=headers)
    with urllib.request.urlopen(req, timeout=5) as r:
        return r.status, r.read().decode()


def _post(base, path, payload, token=TOKEN):
    headers = {'Content-Type': 'application/json'}
    if token is not None:
        headers['X-Panel-Token'] = token
    req = urllib.request.Request(
        base + path, data=json.dumps(payload).encode(),
        headers=headers, method='POST')
    with urllib.request.urlopen(req, timeout=5) as r:
        return r.status, json.loads(r.read().decode())


# ── state building ──────────────────────────────────────────────────────────

def test_build_state_exposes_task_sheet(tasks):
    state = task_gui.build_state(tasks, remaining_seconds=1800)

    assert state['count'] == 3
    assert state['total_points'] == 45
    assert state['remaining_seconds'] == 1800
    assert [t['n'] for t in state['tasks']] == [1, 2, 3]
    assert state['tasks'][0]['description'].startswith('Create a 1GiB')


def test_build_state_includes_category_for_the_collapsed_row(tasks):
    """The category is all the candidate sees before opening a task, so it
    must be present and human-readable."""
    state = task_gui.build_state(tasks)
    labels = [t['category'] for t in state['tasks']]

    assert all(labels), "every row needs a category label"
    assert all('_' not in l for l in labels), labels


def test_build_state_handles_no_exam():
    state = task_gui.build_state([])
    assert state['count'] == 0
    assert state['tasks'] == []
    assert state['total_points'] == 0


def test_build_state_survives_malformed_tasks():
    """A task object missing attributes must not take the panel down
    mid-exam."""
    class Bare:
        pass

    state = task_gui.build_state([Bare()])
    assert state['count'] == 1
    assert state['tasks'][0]['description'] == ''
    assert state['tasks'][0]['points'] == 0


# ── marks ───────────────────────────────────────────────────────────────────

def test_done_and_revisit_are_independent(tasks):
    """Mid-exam you often want both on one task: 'I did something, but come
    back to it'."""
    task_gui.set_mark('lvm_001', 'done', True)
    task_gui.set_mark('lvm_001', 'revisit', True)

    marks = task_gui.marks_for('lvm_001')
    assert marks == {'done': True, 'revisit': True}


def test_unticking_leaves_the_other_mark_alone():
    task_gui.set_mark('lvm_001', 'done', True)
    task_gui.set_mark('lvm_001', 'revisit', True)
    task_gui.set_mark('lvm_001', 'done', False)

    assert task_gui.marks_for('lvm_001') == {'done': False, 'revisit': True}


def test_marks_appear_in_state_and_counts(tasks):
    task_gui.set_mark('lvm_001', 'done', True)
    task_gui.set_mark('part_002', 'revisit', True)
    task_gui.set_mark('sel_003', 'done', True)

    state = task_gui.build_state(tasks)
    assert state['done_count'] == 2
    assert state['revisit_count'] == 1
    assert state['tasks'][0]['done'] is True
    assert state['tasks'][1]['revisit'] is True


def test_unknown_mark_field_rejected():
    with pytest.raises(ValueError):
        task_gui.set_mark('lvm_001', 'passed', True)
    with pytest.raises(ValueError):
        task_gui.set_mark('', 'done', True)


def test_clear_marks_resets_between_exams(tasks):
    task_gui.set_mark('lvm_001', 'done', True)
    task_gui.clear_marks()
    assert task_gui.build_state(tasks)['done_count'] == 0


# ── HTTP surface ────────────────────────────────────────────────────────────

def test_serves_the_page(panel):
    _, base = panel
    status, body = _get(base, '/')
    assert status == 200
    assert '<title>RHCSA Mock Exam' in body
    # Fully self-contained: no external assets to fetch on an offline VM.
    assert 'http://' not in body.split('<style>')[1].split('</style>')[0]
    # Styling only — it must never present itself as the real exam.
    assert 'Red Hat' not in body.replace(
        'Styled after the Red Hat test-exam sheet', '').replace(
        'NOT Red Hat branded', '')


def test_state_endpoint_returns_json(panel):
    _, base = panel
    status, body = _get(base, '/api/state')
    assert status == 200
    state = json.loads(body)
    assert state['count'] == 3
    assert state['remaining_seconds'] == 3600


def test_mark_endpoint_records_a_tick(panel):
    _, base = panel
    status, body = _post(base, '/api/mark',
                         {'id': 'lvm_001', 'field': 'done', 'value': True})
    assert status == 200
    assert body['marks']['done'] is True

    _, state = _get(base, '/api/state')
    assert json.loads(state)['done_count'] == 1


def test_mark_endpoint_rejects_unknown_field(panel):
    _, base = panel
    with pytest.raises(urllib.error.HTTPError) as e:
        _post(base, '/api/mark', {'id': 'lvm_001', 'field': 'score', 'value': 1})
    assert e.value.code == 400


def test_unknown_route_is_404(panel):
    _, base = panel
    with pytest.raises(urllib.error.HTTPError) as e:
        _get(base, '/api/tasks')
    assert e.value.code == 404


def test_panel_exposes_no_shell_route(panel):
    """The panel drives the session through named actions only — there is no
    general command channel, and never should be."""
    _, base = panel
    for path in ('/api/exec', '/api/run', '/api/command', '/shell'):
        with pytest.raises(urllib.error.HTTPError) as e:
            _get(base, path)
        assert e.value.code == 404, path


# ── failure behaviour ───────────────────────────────────────────────────────

def test_state_provider_failure_degrades_instead_of_500(tasks):
    """A panel that breaks must not become a second problem mid-exam."""
    def boom():
        raise RuntimeError("session went away")

    p = task_gui.TaskPanel(boom, port=0, bind='127.0.0.1', token='')
    urls = p.start()
    try:
        status, body = _get(urls[0].rstrip('/'), '/api/state', token=None)
        assert status == 200
        assert json.loads(body)['tasks'] == []
    finally:
        p.stop()


def test_port_already_in_use_returns_no_urls(tasks):
    first = task_gui.TaskPanel(lambda: task_gui.build_state(tasks),
                               port=0, bind='127.0.0.1', token='')
    assert first.start()
    port = first._httpd.server_address[1]
    try:
        second = task_gui.TaskPanel(lambda: task_gui.build_state(tasks),
                                    port=port, bind='127.0.0.1', token='')
        assert second.start() == [], "should fail quietly, not raise"
        assert second.running is False
    finally:
        first.stop()


def test_stop_is_idempotent(tasks):
    p = task_gui.TaskPanel(lambda: task_gui.build_state(tasks),
                           port=0, bind='127.0.0.1', token='')
    p.start()
    p.stop()
    p.stop()
    assert p.running is False


def test_start_for_session_never_raises():
    class BadSession:
        @property
        def tasks(self):
            raise RuntimeError("boom")

    panel, urls = task_gui.start_for_session(BadSession(), port=0,
                                             bind='127.0.0.1')
    if panel:
        panel.token = panel.token  # keep the generated token for the request
    try:
        # It binds fine; the failure only shows up per-request, degraded.
        if urls:
            base = urls[0].split('?')[0].rstrip('/')
            status, body = _get(base, '/api/state', token=panel.token)
            assert status == 200
            assert json.loads(body)['tasks'] == []
    finally:
        if panel:
            panel.stop()


# ── exam-sheet fidelity ─────────────────────────────────────────────────────

def test_tasks_carry_their_target_host(tasks):
    """The sheet is banner-grouped by machine ('Perform the following tasks
    on <host>'), so every task needs to know which box it belongs to."""
    state = task_gui.build_state(tasks)
    assert all(t['host'] for t in state['tasks'])


def test_lab_machine_tasks_report_a_different_host(tasks, monkeypatch):
    remote = FakeTask('rem_004', 'Set the hostname on the lab machine.',
                      category='remote')
    remote.requires_lab_machine = True
    monkeypatch.setattr(task_gui, '_local_host', lambda: 'node1.example.com')

    state = task_gui.build_state(tasks + [remote])
    hosts = {t['host'] for t in state['tasks']}
    assert 'node1.example.com' in hosts
    assert len(hosts) == 2, hosts


def test_row_labels_do_not_leak_the_task(panel):
    """Collapsed rows are generic like the real sheet — the list must not
    let you triage without opening each task."""
    _, base = panel
    _, body = _get(base, '/')
    assert 'class="label">Task ' in body
    assert 'Create a 1GiB logical volume' not in body  # comes from /api/state


# ── reachable-URL advertising ───────────────────────────────────────────────

def test_documentation_range_addresses_are_not_advertised(monkeypatch):
    """The simulator's own networking tasks put TEST-NET-1 addresses on dummy
    interfaces, and this used to advertise http://192.0.2.10:8080/ as the URL
    to open."""
    monkeypatch.setattr(task_gui, '_probe', lambda cmd, timeout=5: (
        '1: lo    inet 127.0.0.1/8 scope host lo\n'
        '2: ens160    inet 192.168.21.128/24 scope global ens160\n'
        '3: dummy0    inet 192.0.2.10/24 scope global dummy0\n'
    ))
    assert task_gui._host_addresses() == ['192.168.21.128']

    urls = task_gui._local_addresses(8080)
    assert 'http://192.168.21.128:8080/' in urls
    assert not any('192.0.2.10' in u for u in urls)


def test_link_local_is_not_advertised(monkeypatch):
    monkeypatch.setattr(task_gui, '_probe', lambda cmd, timeout=5: (
        '2: ens160    inet 169.254.3.4/16 scope global ens160\n'))
    assert task_gui._host_addresses() == []


def test_loopback_url_always_offered(monkeypatch):
    monkeypatch.setattr(task_gui, '_probe', lambda cmd, timeout=5: None)
    monkeypatch.setattr(task_gui, '_host_addresses', lambda: [])
    assert task_gui._local_addresses(8080) == ['http://127.0.0.1:8080/']


# ── firewall awareness ──────────────────────────────────────────────────────

def test_firewall_blocks_when_port_closed(monkeypatch):
    def fake(cmd, timeout=5):
        if 'is-active' in cmd:
            return 'active\n'
        if cmd[0] == 'firewall-cmd':
            return '\n'          # nothing open, as on a stock RHEL/Alma box
        return None
    monkeypatch.setattr(task_gui, '_probe', fake)
    assert task_gui.firewall_blocks(8080) is True


def test_firewall_does_not_block_when_port_open(monkeypatch):
    def fake(cmd, timeout=5):
        if 'is-active' in cmd:
            return 'active\n'
        if cmd[0] == 'firewall-cmd':
            return '8080/tcp 443/tcp\n'
        return None
    monkeypatch.setattr(task_gui, '_probe', fake)
    assert task_gui.firewall_blocks(8080) is False


def test_no_firewall_warning_when_firewalld_inactive(monkeypatch):
    monkeypatch.setattr(task_gui, '_probe',
                        lambda cmd, timeout=5: 'inactive\n' if 'is-active' in cmd else None)
    assert task_gui.firewall_blocks(8080) is False


def test_firewall_check_never_opens_the_port(monkeypatch):
    """This simulator grades firewall tasks — the panel must never touch
    firewalld, only report on it."""
    seen = []

    def fake(cmd, timeout=5):
        seen.append(cmd)
        return 'active\n' if 'is-active' in cmd else '\n'

    monkeypatch.setattr(task_gui, '_probe', fake)
    task_gui.firewall_blocks(8080)
    flat = ' '.join(' '.join(c) for c in seen)
    for mutating in ('--add-port', '--reload', '--permanent', '--remove-port'):
        assert mutating not in flat, seen


# ── theme ───────────────────────────────────────────────────────────────────

def test_theme_toggle_present_and_overrides_the_os_preference(panel):
    """Dark/light must be switchable in the page: the exam VM's browser often
    has no desktop theme to follow, and the viewer may just want the other
    one. data-theme has to win over prefers-color-scheme in BOTH directions."""
    _, base = panel
    _, body = _get(base, '/')

    assert 'id="theme"' in body
    assert ':root[data-theme="light"]' in body
    assert ':root[data-theme="dark"]' in body
    # The OS preference must not beat an explicit choice.
    assert ':root:not([data-theme])' in body
    assert 'localStorage' in body


# ── authentication ──────────────────────────────────────────────────────────

def test_requests_without_the_token_are_refused(panel):
    """The panel binds 0.0.0.0 by default and can now reset the lab and file
    GitHub issues — reachability is not authorisation."""
    _, base = panel
    for path in ('/', '/api/state'):
        with pytest.raises(urllib.error.HTTPError) as e:
            _get(base, path, token=None)
        assert e.value.code == 403, path


def test_wrong_token_refused(panel):
    _, base = panel
    with pytest.raises(urllib.error.HTTPError) as e:
        _get(base, '/api/state', token='not-the-token')
    assert e.value.code == 403


def test_control_endpoints_require_the_token(panel, controller):
    _, base = panel
    for path, body in [('/api/validate', {}),
                       ('/api/reset-lab', {'confirm': True}),
                       ('/api/dispute', {'task_id': 'x', 'argument': 'y'})]:
        with pytest.raises(urllib.error.HTTPError) as e:
            _post(base, path, body, token=None)
        assert e.value.code == 403, path
    assert controller.calls == [], "an unauthorised request reached the controller"


def test_token_accepted_in_the_query_string(panel):
    """The URL the exam prints carries ?t=, so a plain browser GET works."""
    _, base = panel
    status, _ = _get(base + f'/api/state?t={TOKEN}', '', token=None)
    assert status == 200


def test_urls_carry_the_token(tasks, controller):
    p = task_gui.TaskPanel(lambda: task_gui.build_state(tasks),
                           controller=controller, port=0, bind='127.0.0.1')
    try:
        urls = p.start()
        assert urls and all('?t=' in u for u in urls)
        assert len(p.token) >= 16
    finally:
        p.stop()


# ── control actions ─────────────────────────────────────────────────────────

def test_submit_queues_validation(panel, controller):
    _, base = panel
    status, body = _post(base, '/api/validate', {})
    assert status == 200
    assert body['queued'] is True
    assert ('request_validate',) in controller.calls


def test_reset_requires_confirmation(panel, controller):
    """Destructive, and reachable over the network — it must not fire on a
    bare request."""
    _, base = panel
    _, body = _post(base, '/api/reset-lab', {})
    assert body['ok'] is False
    assert 'confirm' in body['error'].lower()

    _, body = _post(base, '/api/reset-lab', {'confirm': True})
    assert body['ok'] is True


def test_dispute_passes_checks_and_argument_through(panel, controller):
    _, base = panel
    _, body = _post(base, '/api/dispute', {
        'task_id': 'lvm_001', 'checks': ['size_correct'],
        'argument': 'the check greps for the wrong fs', 'submit': False})
    assert body['saved_to'].endswith('lvm_001.md')
    call = [c for c in controller.calls if c[0] == 'file_dispute'][0]
    assert call[1] == 'lvm_001'
    assert call[2] == ('size_correct',)
    assert call[4] is False


def test_actions_report_501_without_a_controller(tasks):
    """A panel with no controller must say so rather than pretend it acted."""
    p = task_gui.TaskPanel(lambda: task_gui.build_state(tasks),
                           port=0, bind='127.0.0.1', token='')
    try:
        p.start()
        base = p.urls()[0].split('?')[0].rstrip('/')
        with pytest.raises(urllib.error.HTTPError) as e:
            _post(base, '/api/validate', {}, token=None)
        assert e.value.code == 501
    finally:
        p.stop()


def test_page_exposes_the_control_ui(panel):
    _, base = panel
    _, body = _get(base, '/')
    for marker in ('id="submit"', 'id="resetlab"', 'data-act="dispute"',
                   'X-Panel-Token'):
        assert marker in body, marker
