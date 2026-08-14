"""
Actions the browser task panel can perform on a live exam session.

The panel used to be a read-only view of the question sheet. It now drives
the session — submit for grading, dispute a check, reset the lab — and this
module is the whole of what it is allowed to do. There is deliberately no
general command channel: the panel calls named methods here, nothing else.

THREADING
---------
Requests arrive on HTTP worker threads. Validation runs real commands and
mutates session state, so it must not happen there — request_validate()
only sets an Event, and the main exam thread (which is otherwise blocked
waiting for the candidate to press Enter) picks it up and does the work.
That keeps a single grader, whichever way the submit was triggered.

Reset is the opposite case: it is fast enough to run inline, but it is
destructive, so it refuses while an exam is in progress unless the caller
confirms.
"""

import logging
import threading

logger = logging.getLogger(__name__)


class PanelController:
    """Bridge between the HTTP panel and an ExamSession."""

    def __init__(self, session):
        self.session = session
        # Set by the panel, consumed by the main exam thread.
        self.submit_requested = threading.Event()
        self._dispute_lock = threading.Lock()

    # ── grading ─────────────────────────────────────────────────────────

    def request_validate(self):
        """Ask the main thread to grade the exam. Idempotent."""
        status = getattr(self.session, 'panel_status', 'in_progress')
        if status in ('validating', 'complete'):
            return {'queued': False, 'status': status,
                    'message': 'Already submitted'}
        self.session.panel_status = 'validating'
        self.submit_requested.set()
        logger.info("panel requested validation")
        return {'queued': True, 'status': 'validating'}

    # ── disputes ────────────────────────────────────────────────────────

    def file_dispute(self, task_id, check_names, argument, submit=True):
        """Raise a checker dispute for one task.

        The local report is written before any network call and is kept even
        if submitting fails, so evidence is never lost to a flaky connection.
        The AI reviewer's verdict comes back as a comment on the GitHub
        issue — it does not flow back into the simulator, so the caller gets
        the issue URL to follow.
        """
        from core import dispute

        if not task_id:
            return {'ok': False, 'error': 'task_id is required'}

        record = self._result_for(task_id)
        if not record:
            return {'ok': False,
                    'error': f'No graded result for {task_id} to dispute. '
                             f'Submit the exam first.'}

        wanted = set(check_names or [])
        disputed = [c for c in record.get('checks', [])
                    if not wanted or c.get('name') in wanted]
        if not disputed:
            return {'ok': False, 'error': 'No matching checks to dispute'}

        with self._dispute_lock:
            try:
                evidence = dispute.collect_evidence(record.get('category', ''))
                body = dispute.build_report(record, disputed, argument, evidence)
                path = dispute.save_report(record, body)
            except Exception as e:
                logger.warning("dispute report failed: %s", e)
                return {'ok': False, 'error': f'Could not build report: {e}'}

            result = {'ok': True, 'saved_to': path, 'submitted': False,
                      'issue_url': None}

            if not submit:
                result['message'] = ('Saved locally. Not submitted — no GitHub '
                                     'issue was opened.')
                return result

            if not dispute.gh_available():
                result['message'] = (
                    'Saved locally. The GitHub CLI (gh) is not available or '
                    'not authenticated, so no issue was opened. The report is '
                    'complete and can be filed later.')
                return result

            try:
                ok, info = dispute.submit_issue(record, path)
            except Exception as e:
                logger.warning("dispute submit failed: %s", e)
                ok, info = False, str(e)

            result['submitted'] = bool(ok)
            if ok:
                result['issue_url'] = info
                result['message'] = (
                    'Issue opened. The AI reviewer posts its verdict as a '
                    'comment there — it does not appear in the simulator.')
            else:
                result['message'] = (
                    f'Saved locally, but submitting failed: {info}. The '
                    f'evidence is preserved at {path}.')
            return result

    def list_disputes(self):
        """Reports filed on this box, newest first.

        Disputes are otherwise fire-and-forget — there is no command to list
        what you have filed — so the panel showing them is the only place
        that gap is closed. Verdicts still live on GitHub.
        """
        import os
        from core import dispute

        entries = []
        try:
            names = sorted(os.listdir(dispute.DISPUTE_DIR), reverse=True)
        except OSError:
            names = []
        for name in names:
            if not name.endswith('.md'):
                continue
            path = os.path.join(dispute.DISPUTE_DIR, name)
            try:
                stamp = os.path.getmtime(path)
            except OSError:
                stamp = 0
            entries.append({'file': name, 'path': path, 'mtime': stamp})
        return {'disputes': entries, 'dir': dispute.DISPUTE_DIR}

    # ── lab reset ───────────────────────────────────────────────────────

    def reset_lab(self, confirm=False):
        """Return the box to a clean practice state.

        Destructive, so it is gated twice: the caller must pass confirm, and
        it refuses outright during a running exam — resetting mid-exam would
        delete the very state the candidate is being graded on, and a stray
        request must not be able to do that.
        """
        status = getattr(self.session, 'panel_status', 'in_progress')
        if status == 'in_progress' and getattr(self.session, 'tasks', None):
            return {'ok': False,
                    'error': 'An exam is in progress. Submit it first — '
                             'resetting now would destroy the work being '
                             'graded.'}
        if not confirm:
            return {'ok': False, 'error': 'confirmation required'}

        from core import task_env
        try:
            task_env.session_reset(verbose=False)
        except Exception as e:
            logger.warning("panel lab reset failed: %s", e)
            return {'ok': False, 'error': str(e)}
        logger.info("panel reset the lab environment")
        return {'ok': True,
                'message': 'Lab environment reset: practice mounts, loop '
                           'devices and leftover task artifacts cleared.'}

    # ── helpers ─────────────────────────────────────────────────────────

    def _result_for(self, task_id):
        for record in (getattr(self.session, 'panel_results', None) or {}).get(
                'tasks', []):
            if record.get('task_id') == task_id:
                return record
        return None


def serialize_results(tasks, validation_results, score, max_score, passed):
    """Flatten graded results into something the panel can render.

    Deliberately the same shape core/dispute.py expects for a task record, so
    a dispute raised from the panel carries exactly what one raised from the
    terminal does.
    """
    records = []
    for task, result in zip(tasks, validation_results or []):
        records.append({
            'task_id': getattr(task, 'id', ''),
            'category': getattr(task, 'category', ''),
            'difficulty': getattr(task, 'difficulty', ''),
            'description': getattr(task, 'description', ''),
            'domain': getattr(task, 'exam_domain', 0),
            'score': getattr(result, 'score', 0),
            'max_score': getattr(result, 'max_score', 0),
            'passed': bool(getattr(result, 'passed', False)),
            'checks': [
                {
                    'name': getattr(c, 'name', ''),
                    'passed': bool(getattr(c, 'passed', False)),
                    'points': getattr(c, 'points', 0),
                    'max_points': getattr(c, 'max_points',
                                          getattr(c, 'points', 0)),
                    'message': getattr(c, 'message', ''),
                }
                for c in (getattr(result, 'checks', None) or [])
            ],
        })

    percentage = (score / max_score * 100) if max_score else 0
    return {
        'score': score,
        'max_score': max_score,
        'percentage': round(percentage, 1),
        'passed': bool(passed),
        'tasks': records,
    }
