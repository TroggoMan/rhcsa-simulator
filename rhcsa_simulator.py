#!/usr/bin/env python3
"""
RHCSA EX200 v10 Exam Simulator v4.0.0 - Main Entry Point

Features:
- 188 tasks across 25 categories, 8 EX200 v10 domains
- SM-2 spaced repetition for adaptive practice
- Reboot simulation with persistence validation
- SQLite-backed progress tracking (ResultsDB)
"""

import sys
import os
import logging
import argparse

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from config import settings


def parse_args():
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description=f'{settings.APP_NAME} v{settings.VERSION}',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Quick Start Examples:
  %(prog)s --quick              5 random tasks (task panel in a window)
  %(prog)s --quick lvm          5 LVM tasks
  %(prog)s --exam               Full mock exam
  %(prog)s --exam --no-gui      Same, terminal only
  %(prog)s --exam-version 9     Simulate EX200 v9 (RHEL 9): adds containers
  %(prog)s --learn              Domain-based study mode
  %(prog)s --practice lvm       Practice LVM category
  %(prog)s --adaptive           SM-2 driven weak-area practice
        """
    )

    parser.add_argument('--quick', nargs='?', const='all', metavar='CATEGORY',
                        help='Quick practice (5 tasks). Optionally specify category.')
    parser.add_argument('--exam', action='store_true',
                        help='Start mock exam immediately')
    parser.add_argument('--learn', nargs='?', const='all', metavar='CATEGORY',
                        help='Learn mode. Optionally specify category.')
    parser.add_argument('--practice', metavar='CATEGORY',
                        help='Start practice mode for a category')
    parser.add_argument('--adaptive', action='store_true',
                        help='Start adaptive practice (SM-2 driven)')
    parser.add_argument('--list-categories', action='store_true',
                        help='List available categories and domains')
    parser.add_argument('--export-code', action='store_true',
                        help='Print a portable progress code (backup) and exit')
    parser.add_argument('--import-code', metavar='CODE',
                        help='Restore progress from a code (use "-" to read from stdin)')
    parser.add_argument('--import-mode', choices=['replace', 'merge'],
                        default='replace',
                        help='How --import-code applies (default: replace)')
    # The task panel is ON by default in every mode: the real exam puts its
    # questions in a window of their own, so that is the honest default for a
    # simulator. (We serve ours to a browser; Red Hat's is a native app. The
    # window is the point, not the technology.) --no-gui opts out; if the
    # panel can't bind (e.g. port in use) it falls back to the terminal sheet
    # automatically. Both flags write the same dest, so whichever comes last
    # wins.
    from core.task_gui import DEFAULT_PORT as GUI_PORT
    parser.add_argument('--gui', nargs='?', const=GUI_PORT, type=int,
                        default=GUI_PORT, metavar='PORT',
                        help=f'Port for the task panel (default {GUI_PORT}). '
                             f'On by default in every mode; pass a port only '
                             f'to move it.')
    parser.add_argument('--no-gui', dest='gui', action='store_const', const=None,
                        help='Run in the terminal only, with no task panel '
                             'window')
    parser.add_argument('--gui-bind', default='0.0.0.0', metavar='ADDR',
                        help='Address the task panel listens on '
                             '(default 0.0.0.0, so a headless exam VM can be '
                             'read from your laptop; use 127.0.0.1 to keep it '
                             'local)')
    # Which EX200 to simulate. v10 is the default because it is the current
    # exam; v9 candidates get containers and MBR, and lose Flatpak and
    # systemd timers.
    parser.add_argument('--exam-version', type=int, metavar='N',
                        choices=settings.SUPPORTED_EXAM_VERSIONS,
                        default=settings.DEFAULT_EXAM_VERSION,
                        help=f'EX200 version to simulate: '
                             f'{" or ".join(str(v) for v in settings.SUPPORTED_EXAM_VERSIONS)} '
                             f'(default {settings.DEFAULT_EXAM_VERSION})')
    parser.add_argument('--version', action='version',
                        version=f'%(prog)s {settings.VERSION}')

    return parser.parse_args()


def run_quick_practice(category=None, gui_port=None, gui_bind='0.0.0.0'):
    """Run quick practice - a short session (4-20 tasks) with ResultsDB tracking."""
    from tasks.registry import TaskRegistry
    from core import task_gui
    from core.validator import get_validator
    from core.results_db import get_results_db
    from core import task_env
    from utils import formatters as fmt
    from utils.helpers import confirm_action, select_task_count

    TaskRegistry.initialize()
    db = get_results_db()

    fmt.clear_screen()
    fmt.print_header("QUICK PRACTICE")

    if category and category != 'all':
        print(f"{fmt.format_category_name(category)} tasks.")
    else:
        print("Random tasks across all categories.")
    print()

    count = select_task_count(default=5)
    print()

    if not confirm_action("Ready to start?", default=True):
        return

    # Get tasks
    if category and category != 'all':
        tasks = TaskRegistry.get_practice_tasks(category, 'exam', count)
    else:
        tasks = TaskRegistry.get_exam_tasks(count)

    if not tasks:
        print(fmt.error("Could not generate tasks"))
        return

    validator = get_validator()
    completed = 0
    passed = 0

    # Put the box into the same real state exam/practice/adaptive modes do:
    # clean slate + package offer up front, then inject each task's fault /
    # negative precondition right before the candidate works on it. All system
    # changes are reverted ONCE, at the end of the session (finally below).
    print(fmt.dim("Preparing a clean practice environment..."))
    task_env.prepare_session(tasks)

    panel = task_gui.open_panel(tasks, gui_port, gui_bind)

    try:
        for i, task in enumerate(tasks, 1):
            # Break something to fix / establish the precondition BEFORE the
            # candidate works on it (setup output is generic — no spoilers).
            task_env.setup_task(task)
            fmt.clear_screen()
            print(f"Quick Practice - Task {i}/{len(tasks)}")
            print("=" * 60)
            print()
            print(fmt.bold("Task:"))
            print(task.description)
            print()

            cat_name = fmt.format_category_name(task.category)
            domain = getattr(task, 'exam_domain', 0)
            domain_name = settings.EXAM_DOMAINS.get(domain, "")
            print(fmt.bold(f"Category: {cat_name} [D{domain}]"))
            if domain_name:
                print(fmt.bold(f"Domain: {domain_name}"))
            print(fmt.bold(f"Points: {task.points}"))
            print()

            if task.hints and confirm_action("Show hints?", default=False):
                print()
                for j, hint in enumerate(task.hints, 1):
                    print(f"  {j}. {hint}")
                print()

            input("Complete the task, then press Enter to validate...")

            result = validator.validate_task(task)
            completed += 1

            print()
            if result.passed:
                passed += 1
                print(fmt.success(f"PASSED - {result.score}/{result.max_score} points"))
            else:
                print(fmt.error(f"FAILED - {result.score}/{result.max_score} points"))
                for check in result.checks:
                    if not check.passed:
                        print(f"    - {check.message}")

            # Save to ResultsDB
            db.save_practice_attempt(
                task_id=task.id,
                category=task.category,
                difficulty=task.difficulty,
                domain=getattr(task, 'exam_domain', 0),
                score=result.score,
                max_score=result.max_score,
                passed=result.passed,
                mode='quick'
            )

            # Show exam tips
            exam_tips = getattr(task, 'exam_tips', [])
            if exam_tips:
                print()
                print(fmt.bold("Exam Tips:"))
                for tip in exam_tips:
                    print(f"  * {tip}")

            # Wipe practice disks between disk tasks so the next one gets a
            # clean, signature-free device (other changes revert at session end).
            if getattr(task, 'disk_slots', 0) > 0 and i < len(tasks):
                print(fmt.dim("Re-provisioning practice disks for the next task..."))
                task_env.reset_after_task(task)

            print()
            nxt = input("Press Enter to continue ('b' flags this task as bad, "
                        "'q' quits): ").strip().lower()
            if nxt == 'b':
                from core import task_flags
                reason = input("Why is it bad? (optional): ").strip()
                task_flags.flag(task.id, reason)
                print(fmt.success(f"Flagged '{task.id}' — it won't be offered "
                                  "again (unflag in Setup → Task Statistics)."))
            elif nxt == 'q':
                break
    finally:
        # However the session ends (finished, quit, or Ctrl-C), leave a clean
        # box — reverse all faults/preconditions and remove artifacts.
        task_env.session_teardown(tasks)
        task_gui.close_panel(panel)

    # Summary
    print()
    fmt.print_header("QUICK PRACTICE COMPLETE")
    print(f"Tasks completed: {completed}/{len(tasks)}")
    print(f"Tasks passed: {passed}/{completed}")
    if completed > 0:
        print(f"Success rate: {passed / completed * 100:.0f}%")
    print()


def main():
    """Main application entry point."""
    from utils.logging import setup_logging
    setup_logging()
    logger = logging.getLogger(__name__)

    args = parse_args()

    # Set the exam version before anything reads the task registry or the
    # objective tables — task filtering, domain weighting and Learn mode all
    # key off it.
    settings.set_exam_version(args.exam_version)

    # Handle --list-categories without root
    if args.list_categories:
        from tasks.registry import TaskRegistry
        TaskRegistry.initialize()

        print(f"\n{settings.APP_NAME} v{settings.VERSION}")
        print(f"Available categories ({TaskRegistry.get_task_count()} tasks total):\n")

        for domain_num in sorted(settings.EXAM_DOMAINS.keys()):
            domain_name = settings.EXAM_DOMAINS[domain_num]
            domain_cats = [
                cat for cat, dom in settings.CATEGORY_TO_DOMAIN.items()
                if dom == domain_num and cat in TaskRegistry.get_all_categories()
            ]
            if domain_cats:
                print(f"  Domain {domain_num}: {domain_name}")
                for cat in sorted(domain_cats):
                    count = TaskRegistry.get_task_count(cat)
                    print(f"    {cat}: {count} tasks")
                print()
        return 0

    # Progress snapshot codes — operate only on the local results DB, so they
    # run without the full root/system checks (handy for scripting a snapshot
    # save/restore around a VM revert or reinstall).
    if getattr(args, 'export_code', False):
        from core import progress_code
        try:
            print(progress_code.export_code())
            return 0
        except Exception as e:
            print(f"Error exporting progress code: {e}", file=sys.stderr)
            return 1

    if getattr(args, 'import_code', None):
        from core import progress_code
        code = args.import_code
        if code == '-':
            code = sys.stdin.read()
        try:
            counts, summary = progress_code.import_code(
                code, mode=getattr(args, 'import_mode', 'replace'))
        except progress_code.ProgressCodeError as e:
            print(f"Invalid progress code: {e}", file=sys.stderr)
            return 1
        except Exception as e:
            print(f"Error importing progress code: {e}", file=sys.stderr)
            return 1
        print(f"Imported ({args.import_mode}): {counts['exams']} exams, "
              f"{counts['tasks']} exam tasks, {counts['practice']} attempts, "
              f"{counts['weak']} categories.")
        return 0

    # Check root privileges
    try:
        from utils.helpers import require_root
        require_root()
    except SystemExit:
        return 1

    # Best-effort: capture a known-good /etc/fstab baseline so the fstab guard
    # (tools/rhcsa-fstab-guard.sh) can strip leftover practice/fault entries if a
    # session is ever interrupted. Only captures when none exists and fstab is
    # clean; never fails the launch.
    try:
        import subprocess as _sp
        _guard = '/usr/local/sbin/rhcsa-fstab-guard.sh'
        if os.path.exists(_guard):
            _sp.run([_guard, 'ensure'], capture_output=True, timeout=15)
    except Exception:
        pass

    # Preflight: warn about exam-relevant packages (httpd, vsftpd, nfs-utils,
    # ...) that aren't installed, so a task that assumes one is present
    # doesn't silently fail to set up its scenario. Best-effort, never fails
    # the launch.
    try:
        from core import preflight
        preflight.report_environment()
        preflight.warn_missing()
    except Exception:
        pass

    # A progress autosave (written to /var/lib after every recorded result) that
    # holds more history than the local DB means the install was wiped or the VM
    # reverted since it was written — offer to restore it. This is the moment to
    # say yes: the next completed task overwrites the autosave with local state.
    try:
        from core import progress_code
        from core.results_db import get_results_db
        from utils import formatters as fmt
        db = get_results_db()
        found = progress_code.autosave_has_extra(db)
        if found:
            _code, payload = found
            summary = progress_code.summarize(payload)
            print()
            print(fmt.bold(f"Progress autosave found: {progress_code.AUTOSAVE_PATH}"))
            print("  It contains: " +
                  ", ".join(f"{v} {k}" for k, v in summary.items()))
            print(f"  This install has: {db.get_exam_count()} exams, "
                  f"{db.get_practice_count()} practice attempts.")
            print(fmt.dim("  If you skip, the next completed task overwrites "
                          "the autosave with local state."))
            ans = input("Import it now (merge into local history)? [Y/n]: ")
            if ans.strip().lower() in ('', 'y', 'yes'):
                counts = db.load_progress(payload, mode='merge')
                print(fmt.success(
                    f"Imported: {counts['exams']} exams, {counts['tasks']} exam "
                    f"tasks, {counts['practice']} practice attempts, "
                    f"{counts['weak']} categories."))
            print()
    except Exception:
        pass

    # CLI quick modes
    if args.quick:
        run_quick_practice(args.quick, gui_port=args.gui, gui_bind=args.gui_bind)
        return 0

    if args.exam:
        from core.exam import run_exam_mode
        run_exam_mode(gui_port=args.gui, gui_bind=args.gui_bind)
        return 0

    if args.learn:
        from core.learn import run_learn_mode
        if args.learn != 'all':
            from tasks.registry import TaskRegistry
            TaskRegistry.initialize()
            if args.learn in TaskRegistry.get_all_categories():
                run_learn_mode(category=args.learn, gui_port=args.gui, gui_bind=args.gui_bind)
            else:
                print(f"Unknown category: {args.learn}")
                print("Use --list-categories to see available categories")
                return 1
        else:
            run_learn_mode(gui_port=args.gui, gui_bind=args.gui_bind)
        return 0

    if args.practice:
        from tasks.registry import TaskRegistry
        TaskRegistry.initialize()
        if args.practice in TaskRegistry.get_all_categories():
            from core.practice import PracticeSession
            session = PracticeSession(gui_port=args.gui, gui_bind=args.gui_bind)
            session.category = args.practice
            session.difficulty = 'exam'
            session.start()
        else:
            print(f"Unknown category: {args.practice}")
            print("Use --list-categories to see available categories")
            return 1
        return 0

    if args.adaptive:
        from core.adaptive import run_adaptive_mode
        run_adaptive_mode(gui_port=args.gui, gui_bind=args.gui_bind)
        return 0

    # Note if a previous session's environment is still in place (expected —
    # exams deliberately leave the box as-is for review/disputes).
    try:
        from tasks.troubleshooting import load_fault_state
        stale = load_fault_state()
        if stale:
            from utils import formatters as fmt
            print(fmt.warning(
                "\n! A previous session's environment is still active (kept for "
                "review/disputes)."))
            print(fmt.warning("  Run  Setup → Reset Machine  to clean it up; starting a new"))
            print(fmt.warning("  session also resets it automatically.\n"))
    except Exception:
        pass

    # Interactive menu mode
    from core.menu import MenuSystem
    from core.exam import run_exam_mode
    from core.practice import run_practice_mode
    from core.learn import run_learn_mode
    from core.adaptive import run_adaptive_mode

    menu = MenuSystem()

    while True:
        try:
            choice = menu.display_main_menu()

            if choice == 'learn':
                run_learn_mode(gui_port=args.gui, gui_bind=args.gui_bind)

            elif choice == 'quick_practice':
                run_quick_practice(gui_port=args.gui, gui_bind=args.gui_bind)
                input("\nPress Enter to return to menu...")

            elif choice == 'exam':
                run_exam_mode(gui_port=args.gui, gui_bind=args.gui_bind)
                input("\nPress Enter to return to menu...")

            elif choice == 'practice':
                run_practice_mode(gui_port=args.gui, gui_bind=args.gui_bind)
                input("\nPress Enter to return to menu...")

            elif choice == 'adaptive':
                run_adaptive_mode(gui_port=args.gui, gui_bind=args.gui_bind)

            elif choice == 'boot_rescue':
                from core import boot_rescue
                boot_rescue.interactive()

            elif choice == 'dashboard':
                menu.show_dashboard()

            elif choice == 'export':
                menu.export_report()

            elif choice == 'history':
                menu.show_result_history()

            elif choice == 'snapshot':
                menu.progress_snapshot()

            elif choice == 'setup':
                menu.show_setup()

            elif choice == 'help':
                menu.show_help()

            elif choice == 'exit':
                print(f"\nThank you for using {settings.APP_NAME}!")
                print("Good luck with your certification!")
                return 0

        except KeyboardInterrupt:
            print("\n\nInterrupted by user.")
            confirm = input("Are you sure you want to exit? [y/N]: ").strip().lower()
            if confirm in ['y', 'yes']:
                return 0

        except Exception as e:
            logger.exception("Unexpected error in main loop")
            print(f"\nError: {e}")
            print("Please report this issue if it persists.")
            input("Press Enter to return to menu...")


if __name__ == '__main__':
    sys.exit(main())
