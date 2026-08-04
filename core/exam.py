"""
Exam mode orchestrator for RHCSA Simulator v4.0.0

Features:
- Domain-balanced task generation via TaskRegistry.generate_exam()
- ExamTimer integration with warnings
- Reboot simulation with persistence validation
- ResultsDB storage (SQLite)
- Domain breakdown in final report
"""

import io
import time
import logging
from contextlib import redirect_stdout
from datetime import datetime, timedelta
from config import settings
from tasks.registry import TaskRegistry
from core.validator import get_validator
from core.results_db import get_results_db
from core.reboot_engine import get_reboot_engine
from core.timer import create_exam_timer, TimerDisplay
from utils import formatters as fmt
from utils.helpers import generate_id, format_timedelta, confirm_action


logger = logging.getLogger(__name__)


class ExamSession:
    """
    Exam mode session orchestrator.

    Manages domain-balanced task generation, timer, validation,
    reboot simulation, and ResultsDB persistence.
    """

    def __init__(self, task_count=None, timer_enabled=True, duration_minutes=None,
                 reboot_simulation=None, gui_port=None, gui_bind='0.0.0.0'):
        self.task_count = task_count or settings.DEFAULT_EXAM_TASKS
        # Browser task panel — the exam shows its questions in a window you
        # keep beside your terminals, so practising that is part of the point.
        # None = off (opt-in via --gui).
        self.gui_port = gui_port
        self.gui_bind = gui_bind
        self.panel = None
        self.timer_enabled = timer_enabled
        self.duration_minutes = duration_minutes or settings.DEFAULT_EXAM_DURATION
        self.reboot_simulation = reboot_simulation if reboot_simulation is not None else settings.REBOOT_SIMULATION
        self.start_time = None
        self.end_time = None
        self.tasks = []
        self.exam_id = generate_id("exam")
        self.timer = None
        self._injected_tasks = []
        self._setup_tasks = []

    def start(self):
        """Start the exam session."""
        TaskRegistry.initialize()

        self._display_welcome()

        if not confirm_action("Ready to start the exam?", default=True):
            print("Exam cancelled.")
            return None

        from utils import helpers
        from core import task_env
        # Start from a clean box: restore anything a previous session left in
        # place (exams keep their environment for review/disputes), wipe orphan
        # loop devices, and remove leftover task artifacts.
        task_env.session_reset()
        # Whole-disk tasks are capped by how many practice devices CAN exist,
        # not by the 3 loops a fresh session starts with — loop devices are
        # created on demand in _provision_devices(), so the real bound is free
        # disk space plus any spare non-system real disk (e.g. /dev/sda).
        try:
            disk_budget = (helpers.loop_device_capacity()
                           + len(helpers.get_spare_real_disks()))
        except Exception:
            disk_budget = None

        # Generate domain-balanced tasks
        print("\nGenerating exam tasks...")
        self.tasks = TaskRegistry.generate_exam(self.task_count, disk_budget=disk_budget)

        if not self.tasks:
            print(fmt.error("Error: Could not generate exam tasks"))
            return None

        print(fmt.success(f"Generated {len(self.tasks)} tasks across {self._count_domains()} domains"))

        # Give each whole-disk task a distinct device (no two share one disk)
        self._provision_devices()

        # Offer to install any packages the drawn scenarios rely on. Nothing is
        # installed without the user's consent; tasks whose packages remain
        # missing degrade gracefully (reduced scenario / fabricated evidence).
        from core import preflight
        try:
            preflight.offer_task_packages(self.tasks)
        except Exception:
            pass

        # Inject faults / set up environments for tasks that require it
        self._inject_exam_faults()

        # Establish negative preconditions for positive-config tasks so they
        # can't pass on pre-existing/default state.
        self._setup_task_environments()

        # Sanity-check that setup actually put the box into each task's scenario
        # (no task should already be passing before the candidate starts).
        self._sanity_check_tasks()

        # Refresh the remote NFS server's exports so this exam starts clean.
        self._reprovision_nfs()

        # Bring the browser panel up before the sheet is shown, so the URL is
        # on screen while the candidate still has both hands free.
        self._start_task_panel()

        self._display_tasks()

        # Start timer
        self.start_time = datetime.now()

        if self.timer_enabled:
            self.timer = create_exam_timer(self.duration_minutes)
            self.timer.start()
            end_time = self.start_time + timedelta(minutes=self.duration_minutes)
            print(f"\n{fmt.warning('Timer started!')} You have {self.duration_minutes} minutes.")
            print(f"Exam ends at: {end_time.strftime('%H:%M:%S')}")
            # Uptime-anchored countdown for the candidate's other terminal —
            # exam tasks change the system clock, so `date` can't be trusted.
            from core import exam_clock
            if exam_clock.start(self.duration_minutes):
                print(fmt.dim("Check the time left any time (even after clock/"
                              "timezone tasks): exam-time-left"))
        else:
            print(f"\n{fmt.info('Exam started!')} (No time limit)")

        print("\nComplete the tasks on your system, then return here to validate your work.")
        print("=" * 60)

    def _start_task_panel(self):
        """Serve the task sheet to a browser window. Opt-in, best-effort: a
        panel that won't start must never prevent an exam from running."""
        if not self.gui_port:
            return
        from core import task_gui
        task_gui.clear_marks()
        self.panel, urls = task_gui.start_for_session(
            self, port=self.gui_port, bind=self.gui_bind)
        if not urls:
            print(fmt.warning(
                f"\nTask panel could not start on port {self.gui_port} "
                f"(in use?). Continuing without it — the task sheet below is "
                f"the same content."))
            return
        print()
        print(fmt.success("Task panel running — open it beside your terminals:"))
        for url in urls:
            print(fmt.bold(f"    {url}"))
        if self.gui_bind not in ('127.0.0.1', 'localhost'):
            print(fmt.dim("  (Unauthenticated and reachable from your LAN. It "
                          "serves exam questions only — no shell, no control "
                          "of this box.)"))
            # A stock RHEL/Alma box has firewalld up with nothing open, so
            # the LAN URL above simply won't connect from a laptop. Say so
            # rather than letting the candidate debug it mid-exam. We never
            # open the port ourselves — this simulator grades firewall tasks,
            # and editing firewalld here would corrupt what they check.
            try:
                from core import task_gui
                if task_gui.firewall_blocks(self.gui_port):
                    print(fmt.warning(
                        f"  firewalld is blocking port {self.gui_port}, so only "
                        f"the 127.0.0.1 URL will work from this box."))
                    print(fmt.dim(
                        f"    Reach it from another machine either by "
                        f"forwarding it over SSH (leaves the firewall alone):\n"
                        f"      ssh -L {self.gui_port}:127.0.0.1:"
                        f"{self.gui_port} root@<this-box>\n"
                        f"    or by opening the port yourself. Note that this "
                        f"exam may contain firewall tasks, so the simulator "
                        f"will not change firewalld for you."))
            except Exception:
                pass

    def _stop_task_panel(self):
        if self.panel:
            try:
                self.panel.stop()
            except Exception:
                pass
            self.panel = None

    def _provision_devices(self):
        """Assign a distinct practice device to each whole-disk task so an LVM
        task and a partition task never collide on the same disk."""
        from utils import helpers
        disk_tasks = [t for t in self.tasks if getattr(t, 'disk_slots', 0) > 0]
        if not disk_tasks:
            return
        need = sum(t.disk_slots for t in disk_tasks)
        spares = len(helpers.get_spare_real_disks())
        helpers.begin_device_allocation(min_loops=max(3, need - spares))
        try:
            for t in disk_tasks:
                try:
                    t.provision_devices()
                except Exception:
                    pass
        finally:
            helpers.end_device_allocation()

    def _inject_exam_faults(self):
        """Inject faults / create practice environments for all tasks that need
        it. Output is deliberately generic — printing the task id or the
        injection message would hand the candidate the answer (e.g. "Set wrong
        SELinux context (etc_t) on /var/www/html"). Details go to the log."""
        fault_tasks = [t for t in self.tasks if getattr(t, 'has_fault_injection', False)]
        if not fault_tasks:
            return
        print(fmt.bold("\nPreparing exam environment..."))
        armed = skipped = 0
        for task in fault_tasks:
            try:
                ok, msg = task.inject_fault()
                if ok:
                    self._injected_tasks.append(task)
                    armed += 1
                    logger.info("fault armed: %s: %s", task.id, msg)
                else:
                    skipped += 1
                    logger.warning("fault skipped (descriptive only): %s: %s", task.id, msg)
            except Exception as e:
                skipped += 1
                logger.warning("fault setup error: %s: %s", task.id, e)
        line = f"  {armed} scenario(s) prepared"
        if skipped:
            line += f", {skipped} skipped (details in the log)"
        print(fmt.dim(line))
        print()

    def _setup_task_environments(self):
        """Run setup_environment() for positive-config tasks so they establish a
        negative precondition (stop a default-on service, move an artifact aside)
        and therefore require real work to pass. Output stays generic — the
        setup message describes exactly what was changed (i.e. the answer)."""
        setup_tasks = [t for t in self.tasks if getattr(t, 'has_setup', False)]
        if not setup_tasks:
            return
        prepared = 0
        for task in setup_tasks:
            try:
                ok, msg = task.setup_environment()
                if ok:
                    self._setup_tasks.append(task)
                    prepared += 1
                    logger.info("precondition set: %s: %s", task.id, msg)
                # A False result just means no precondition was needed; the task
                # is still valid, so stay quiet to avoid alarming the candidate.
            except Exception as e:
                logger.warning("precondition error: %s: %s", task.id, e)
        if prepared:
            print(fmt.dim(f"  {prepared} starting state(s) prepared"))

    def _sanity_check_tasks(self):
        """After setup, verify no task is already passing before the candidate
        starts. A pass at t=0 means its fault/precondition no-op'd (or it passes
        on default state) — a free pass. Print only a non-spoiling count here (so
        we don't reveal WHICH tasks need no work); full details go to the log."""
        try:
            from core import task_sanity
            warnings = task_sanity.check_tasks(self.tasks, verbose_console=False)
        except Exception:
            return
        if warnings:
            print(fmt.warning(
                f"  ⚠ {len(warnings)} task(s) may not have initialized correctly "
                f"(see the log). They'll still be scored normally."))

    def _has_nfs_tasks(self):
        return any(getattr(t, 'category', '') == 'network_storage' for t in self.tasks)

    def _reprovision_nfs(self):
        """If a remote NFS server is configured and this exam has NFS tasks,
        refresh its exports so the run starts from clean, seeded shares."""
        if not self._has_nfs_tasks():
            return
        try:
            from core import nfs_server
        except Exception:
            return
        if not nfs_server.load_config():
            return
        print(fmt.bold("\nRefreshing NFS server exports..."))
        try:
            ok, exports, output = nfs_server.reprovision_from_config()
        except Exception as e:
            print(fmt.warning(f"  ✗ NFS re-provision error ({e})"))
            return
        if ok:
            print(fmt.success(f"  ✓ NFS exports refreshed ({len(exports)} shares)"))
        else:
            print(fmt.warning("  ✗ Could not refresh NFS exports (NFS tasks may not be testable):"))
            tail = (output or '').strip().splitlines()[-2:]
            for line in tail:
                print(fmt.dim(f"      {line}"))
            print(fmt.dim("      Fix via Setup → Configure remote NFS server → Test connection."))

    # NOTE: there is deliberately NO automatic teardown at exam end. The
    # environment (injected faults, the candidate's work, NFS mounts) is left
    # in place so scores can be reviewed against live state and checker
    # disputes can capture real evidence. Cleanup happens explicitly via the
    # menu's single "Reset Machine" action, or automatically at the start of
    # the next session.

    def _count_domains(self):
        """Count unique domains in generated tasks."""
        domains = set()
        for task in self.tasks:
            domain = getattr(task, 'exam_domain', 0)
            if domain:
                domains.add(domain)
        return len(domains)

    def _display_welcome(self):
        """Display exam welcome screen."""
        fmt.clear_screen()
        fmt.print_header("RHCSA MOCK EXAM", char='=')

        print(fmt.bold("Exam Information:"))
        print(f"  Tasks: {self.task_count}")
        print(f"  Duration: {self.duration_minutes} minutes" if self.timer_enabled else "  Duration: No time limit")
        print(f"  Pass threshold: {settings.EXAM_PASS_THRESHOLD * 100:.0f}%")
        print(f"  Reboot simulation: {'Enabled' if self.reboot_simulation else 'Disabled'}")
        print()

        print(fmt.bold("Instructions:"))
        print("  1. Read all tasks carefully before starting")
        print("  2. Complete tasks on your Linux system")
        print("  3. Return here when ready to validate")
        print("  4. After validation, a reboot simulation checks persistence")
        print()

        print(fmt.warning("Note: This simulator only validates your work. It does NOT make changes to your system."))
        print()

    def _display_tasks(self):
        """Display all exam tasks through a pager so the full question sheet is
        scrollable (no tmux copy-mode needed for long exams)."""
        total_points = sum(task.points for task in self.tasks)

        buf = io.StringIO()
        with redirect_stdout(buf):
            fmt.print_header("EXAM TASKS")
            for i, task in enumerate(self.tasks, 1):
                domain = getattr(task, 'exam_domain', 0)
                domain_name = settings.EXAM_DOMAINS.get(domain, "")
                domain_tag = f" [{domain_name}]" if domain_name else ""
                fmt.print_task(i, task.description, task.points)
                if domain_tag:
                    print(fmt.dim(f"      Domain {domain}: {domain_name}"))
            print()
            print(fmt.bold(f"Total Points: {total_points}"))
            print(fmt.dim("(Scroll with ↑/↓ or PageUp/PageDown; press q to start.)"))
            print("=" * 60)
        fmt.page_output(buf.getvalue())

    def validate_all(self):
        """Validate all tasks, run reboot simulation, save to ResultsDB."""
        self.end_time = datetime.now()

        # Stop timer
        if self.timer:
            self.timer.stop()
        from core import exam_clock
        exam_clock.stop()

        print()
        fmt.print_header("VALIDATING YOUR WORK")

        validator = get_validator()

        # Phase 1: Initial validation
        validation_results = []
        initial_results_map = {}

        for i, task in enumerate(self.tasks, 1):
            print(f"\nValidating Task {i}/{len(self.tasks)}: {task.id}")
            result = validator.validate_task(task)
            validation_results.append(result)
            initial_results_map[task.id] = result
            self._display_task_result(i, task, result)

        # Calculate initial scores
        total_score, max_score, percentage = validator.calculate_total_score(validation_results)

        # Phase 2: Reboot simulation
        reboot_result = None
        reboot_passed = None

        if self.reboot_simulation:
            print()
            fmt.print_header("REBOOT SIMULATION")
            print("Simulating system reboot to check persistence...")
            print()

            engine = get_reboot_engine()
            reboot_result = engine.simulate_reboot(self.tasks, initial_results_map)

            # Display reboot report
            report = engine.get_reboot_report(reboot_result, self.tasks)
            print(report)

            if not reboot_result.boot_success:
                # Boot failure = automatic fail, score 0
                total_score = 0
                percentage = 0
                reboot_passed = False
            else:
                reboot_passed = True
                # Deduct points for tasks that lost persistence
                for task_id in reboot_result.tasks_lost_points:
                    result = initial_results_map.get(task_id)
                    if result:
                        total_score -= result.score
                percentage = (total_score / max_score * 100) if max_score > 0 else 0

        passed = percentage >= (settings.EXAM_PASS_THRESHOLD * 100)

        # Display final report
        duration = (self.end_time - self.start_time).total_seconds()
        self._display_final_report(
            total_score, max_score, percentage, passed,
            duration, validation_results, reboot_result
        )

        # Deliberately NO cleanup here — the environment stays exactly as the
        # candidate left it so they can re-inspect their work against the
        # scores and file checker disputes with live evidence.
        print()
        print(fmt.info("The exam environment has been left in place so you can "
                       "review your work and dispute any check (Result History → task → 'd')."))
        print(fmt.info("When you're done, run  Setup → Reset Machine  to clean up."))

        # Save to ResultsDB
        db = get_results_db()
        db.save_exam_result(
            exam_id=self.exam_id,
            start_time=self.start_time.isoformat(),
            end_time=self.end_time.isoformat(),
            duration_seconds=int(duration),
            total_score=total_score,
            max_score=max_score,
            passed=passed,
            reboot_passed=reboot_passed,
            task_count=len(self.tasks),
            mode='exam'
        )

        # Save per-task results
        for task, result in zip(self.tasks, validation_results):
            persistence_passed = None
            if reboot_result and task.id in reboot_result.persistence_results:
                persistence_passed = reboot_result.persistence_results[task.id].passed

            checks_data = [c.to_dict() for c in result.checks] if result.checks else None
            db.save_task_result(
                exam_id=self.exam_id,
                task_id=task.id,
                category=task.category,
                difficulty=task.difficulty,
                domain=getattr(task, 'exam_domain', 0),
                description=task.description,
                score=result.score,
                max_score=result.max_score,
                passed=result.passed,
                persistence_passed=persistence_passed,
                checks=checks_data,
                hints=getattr(task, 'hints', None),
                exam_tips=getattr(task, 'exam_tips', None),
            )

        return passed

    def _display_task_result(self, task_num, task, result):
        """Display result for a single task."""
        desc = task.description[:60]
        print(f"\n{fmt.bold(f'Task {task_num}:')} {desc}...")

        for check in result.checks:
            fmt.print_check_result(
                check.name,
                check.passed,
                check.message,
                check.points,
                check.max_points
            )

        status = fmt.success("PASS") if result.passed else fmt.error("FAIL")
        print(f"  Score: {result.score}/{result.max_score} points ({result.percentage:.0f}%) - {status}")

    def _display_final_report(self, total_score, max_score, percentage, passed,
                               duration, validation_results, reboot_result):
        """Display final exam report with domain breakdown."""
        fmt.print_header("EXAM RESULTS")

        # Overall result
        print(fmt.bold("Overall Performance:"))
        print(f"  Total Score: {total_score}/{max_score} points")
        print(f"  Percentage: {percentage:.1f}%")
        tasks_passed = sum(1 for r in validation_results if r.passed)
        print(f"  Tasks Passed: {tasks_passed}/{len(validation_results)}")
        print(f"  Duration: {format_timedelta(timedelta(seconds=int(duration)))}")
        print()

        # Pass/Fail
        threshold_pct = settings.EXAM_PASS_THRESHOLD * 100
        if passed:
            print(fmt.success(f"  PASSED (Required: {threshold_pct:.0f}%)"))
        else:
            print(fmt.error(f"  FAILED (Required: {threshold_pct:.0f}%)"))
        print()

        # Reboot status
        if reboot_result:
            if not reboot_result.boot_success:
                print(fmt.error("  BOOT FAILURE - All points lost"))
            elif reboot_result.tasks_lost_points:
                lost = len(reboot_result.tasks_lost_points)
                print(fmt.warning(f"  {lost} task(s) lost points due to failed persistence"))
            else:
                print(fmt.success("  All persistence checks passed after reboot"))
            print()

        # Domain breakdown
        validator = get_validator()
        task_results = list(zip(self.tasks, validation_results))
        domain_breakdown = validator.get_domain_breakdown(task_results)

        if domain_breakdown:
            print(fmt.bold("Performance by Domain:"))
            for domain_num in sorted(domain_breakdown.keys()):
                stats = domain_breakdown[domain_num]
                pct = stats['percentage']
                name = stats['name']
                print(f"  Domain {domain_num} - {name}: "
                      f"{stats['earned_points']}/{stats['total_points']} pts ({pct:.0f}%)")
            print()

        # Category breakdown
        cat_breakdown = validator.get_category_breakdown(task_results)
        if cat_breakdown:
            print(fmt.bold("Performance by Category:"))
            for category in sorted(cat_breakdown.keys()):
                stats = cat_breakdown[category]
                pct = stats['percentage']
                cat_name = fmt.format_category_name(category)
                print(f"  {cat_name}: {stats['earned_points']}/{stats['total_points']} pts ({pct:.0f}%)")
            print()


def _select_exam_task_count():
    """Prompt user to select exam task count."""
    from utils import formatters as fmt
    print()
    print(fmt.bold("Select number of exam tasks:"))
    print("  1. 20 tasks  — standard (real exam minimum)")
    print("  2. 25 tasks  — full exam (real exam maximum)")
    print("  3. 12 tasks  — quick practice run")
    while True:
        choice = input("\nSelect [1]: ").strip() or '1'
        if choice == '1':
            return 20
        elif choice == '2':
            return 25
        elif choice == '3':
            return 12
        else:
            print(fmt.error("Invalid selection"))


def _select_reboot_simulation():
    """Prompt user to enable or disable reboot simulation."""
    from utils import formatters as fmt
    print()
    print(fmt.bold("Reboot simulation:"))
    print("  1. Enabled   — persistence tasks validated after simulated reboot (recommended)")
    print("  2. Disabled  — skip reboot phase, score initial validation only")
    while True:
        choice = input("\nSelect [1]: ").strip() or '1'
        if choice == '1':
            return True
        elif choice == '2':
            return False
        else:
            print(fmt.error("Invalid selection"))


def run_exam_mode(gui_port=None, gui_bind='0.0.0.0'):
    """Run exam mode (convenience function)."""
    task_count = _select_exam_task_count()
    reboot_sim = _select_reboot_simulation()
    session = ExamSession(task_count=task_count, reboot_simulation=reboot_sim,
                          gui_port=gui_port, gui_bind=gui_bind)
    session.start()

    if not session.tasks:
        session._stop_task_panel()
        return None

    input("\nPress Enter when you're ready to validate your work...")

    try:
        # No teardown on any exit path — the environment persists for review
        # and disputes. The next session start (or Setup → Reset Machine)
        # cleans up.
        return session.validate_all()
    finally:
        # The panel is a view of a running exam; once grading starts it is
        # showing a sheet nobody can act on any more.
        session._stop_task_panel()
