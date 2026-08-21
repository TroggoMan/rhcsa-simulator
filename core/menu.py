"""
Main menu system for RHCSA Simulator v4.0.0

Streamlined 9-option interface with ResultsDB dashboard.
"""

import sys
import textwrap
from utils import formatters as fmt
from config import settings


class MenuSystem:
    """
    Main menu system for the application.

    v4.0.0 Features:
    - 9-option menu aligned with EX200 v10 domains
    - SM-2 adaptive mode integration
    - ResultsDB-powered dashboard
    """

    def display_main_menu(self):
        """Display main menu and get selection."""
        while True:
            fmt.clear_screen()
            self._print_header()

            # Quick Start section
            print(fmt.bold("QUICK START"))
            fmt.print_menu_option('Q', "Quick Practice", "Short session, 4-20 random tasks")
            fmt.print_menu_option('E', "Mock Exam", f"20–25 tasks, {settings.DEFAULT_EXAM_DURATION} min, reboot sim")
            print()

            # Learn & Practice section
            print(fmt.bold("LEARN & PRACTICE"))
            fmt.print_menu_option(1, "Learn Mode", "Domain-based study with SM-2 indicators")
            fmt.print_menu_option(2, "Practice Mode", "Category-focused with retry & hints")
            fmt.print_menu_option(3, "Adaptive Mode", "SM-2 driven weak-area practice")
            fmt.print_menu_option('R', "Boot Rescue Lab", "Recover root on the linked 2nd machine")
            print()

            # Progress section
            print(fmt.bold("PROGRESS"))
            fmt.print_menu_option(4, "Dashboard", "Stats, history & weak areas")
            fmt.print_menu_option(5, "Export Report", "Generate progress report")
            fmt.print_menu_option(6, "Result History", "Drill into past exam results task by task")
            fmt.print_menu_option(7, "Progress Snapshot", "Backup/restore history via a code; prune entries")
            print()

            # Footer
            print(fmt.dim("-" * 50))
            print(fmt.dim("  [S] Setup  [?] Help  [0] Exit"))
            print()

            choice = input("Select option: ").strip().lower()

            if choice == 'q':
                return 'quick_practice'
            elif choice == 'e':
                return 'exam'
            elif choice == '1':
                return 'learn'
            elif choice == '2':
                return 'practice'
            elif choice == '3':
                return 'adaptive'
            elif choice == 'r':
                return 'boot_rescue'
            elif choice == '4':
                return 'dashboard'
            elif choice == '5':
                return 'export'
            elif choice == '6':
                return 'history'
            elif choice == '7':
                return 'snapshot'
            elif choice == 's':
                return 'setup'
            elif choice in ('?', 'h'):
                return 'help'
            elif choice == '0':
                return 'exit'
            else:
                print(fmt.error("Invalid selection."))
                input("Press Enter to continue...")

    def _print_header(self):
        """Print application header."""
        fmt.print_header(f"{settings.APP_NAME} v{settings.VERSION}")

    def show_dashboard(self):
        """Show unified progress dashboard using ResultsDB."""
        from core.results_db import get_results_db

        db = get_results_db()

        fmt.clear_screen()
        fmt.print_header("PROGRESS DASHBOARD")

        # Overall Stats
        exam_count = db.get_exam_count()
        practice_count = db.get_practice_count()
        all_stats = db.get_all_category_stats()

        total_attempts = sum(s['attempts'] for s in all_stats) if all_stats else 0
        total_passes = sum(s['passes'] for s in all_stats) if all_stats else 0
        overall_rate = (total_passes / total_attempts * 100) if total_attempts > 0 else 0

        print(fmt.bold("Overall Performance"))
        print(f"  Exams Taken: {exam_count}")
        print(f"  Practice Attempts: {practice_count}")
        print(f"  Categories Practiced: {len(all_stats)}")
        print(f"  Overall Success Rate: {overall_rate:.0f}%")
        print()

        # Recent Exams
        recent = db.get_recent_exams(5)
        if recent:
            print(fmt.bold("Recent Exams"))
            for r in recent:
                date = r['start_time'][:10] if r['start_time'] else "Unknown"
                pct = r['percentage']
                status = fmt.success("PASS") if r['passed'] else fmt.error("FAIL")
                reboot = ""
                if r['reboot_passed'] is not None:
                    reboot = fmt.success(" [Reboot OK]") if r['reboot_passed'] else fmt.error(" [Boot FAIL]")
                print(f"  {date} - {pct:.0f}% {status}{reboot}")
            print()

        # Weak Areas
        weak = db.get_weak_categories(0.7)
        if weak:
            print(fmt.bold("Weak Areas (below 70%)"))
            for w in weak[:5]:
                cat_name = fmt.format_category_name(w['category'])
                rate = w['success_rate'] * 100
                attempts = w['attempts']
                print(f"  - {cat_name}: {rate:.0f}% ({attempts} attempts)")
            print()

        # Due for Review
        due = db.get_due_categories()
        if due:
            print(fmt.bold(f"Due for Review ({len(due)} categories)"))
            for d in due[:5]:
                cat_name = fmt.format_category_name(d['category'])
                print(f"  - {cat_name}")
            print()

        # Persistence Failures
        pf = db.get_persistence_failure_tasks()
        if pf:
            print(fmt.bold("Frequent Persistence Failures"))
            for p in pf[:3]:
                print(f"  - {p['task_id']} ({p['category']}) - {p['failures']} failures")
            print()

        if not recent and not all_stats:
            print(fmt.info("No data yet. Start practicing to see your progress!"))
            print()

        print(fmt.dim("Press Enter to return..."))
        input()

    def show_help(self):
        """Display help information."""
        fmt.clear_screen()
        fmt.print_header("HELP")

        help_text = f"""
{settings.APP_NAME} v{settings.VERSION} - Quick Guide

QUICK START
  Q - Quick Practice: a short session (4-20 random tasks) with validation.
      Perfect for daily practice sessions.

  E - Mock Exam: {settings.DEFAULT_EXAM_TASKS}-task exam with {settings.DEFAULT_EXAM_DURATION}-min timer.
      Domain-balanced, includes reboot simulation.

LEARN & PRACTICE
  1. Learn Mode - Study EX200 v10 domains with explanations,
     commands, exam tips. SM-2 indicators show weak areas.
  2. Practice Mode - Pick a category, choose difficulty,
     get instant feedback with retry & solution hints.
  3. Adaptive Mode - SM-2 selects your weakest/due categories.
     Difficulty adjusts to your performance. Best for review.
  R. Boot Rescue Lab - the simulator scrambles root's password on a
     linked second machine; you recover it at that machine's console
     (rd.break or init=/bin/bash). Link the machine in Setup first.

PROGRESS
  4. Dashboard - View exam history, success rates, weak areas,
     spaced repetition due dates, persistence failures.
  5. Export Report - Generate a progress report.

EXAM DOMAINS (EX200 v10)
  1. Software Management    2. System Setup & Boot
  3. Users & Permissions    4. Storage & Filesystems
  5. Network & DNS          6. Systemd & Services
  7. SELinux & Firewall     8. Automation & Scripting
  9. Container Management

TIPS
  - Run as root (sudo) for full functionality
  - Practice daily for best results - SM-2 will schedule reviews
  - Adaptive mode is the most effective for exam prep
  - Persistence tasks require config that survives reboot

For RHCSA exam info: https://www.redhat.com/rhcsa
        """

        print(help_text)
        input("Press Enter to return to menu...")

    def show_setup(self):
        """Show setup and configuration options."""
        fmt.clear_screen()
        fmt.print_header("SETUP")

        from core import nfs_server, lab_machine
        cfg = nfs_server.load_config()
        if cfg:
            where = 'this machine (local)' if cfg.get('local') else cfg['host']
            nfs_status = fmt.success(f"configured: {where}")
        else:
            nfs_status = fmt.dim("not configured")
        lab_cfg = lab_machine.load_config()
        lab_status = (fmt.success(f"linked: {lab_cfg['host']}") if lab_cfg
                      else fmt.dim("not linked"))

        print(fmt.bold("Options"))
        print("  1. Setup Practice Disks (loop devices for LVM)")
        print("  2. View Task Statistics")
        print("  3. Network Backup/Restore")
        print("  4. Reset Machine (undo ALL practice changes, back to a clean box)")
        print("  5. Populate Practice Environment (DNF history)")
        print(f"  6. Configure NFS server for NFS tasks ({nfs_status})")
        print(f"  7. Link second lab machine — boot rescue & remote tasks ({lab_status})")
        print("  0. Return to Menu")
        print()

        choice = input("Select option: ").strip()

        if choice == '1':
            self.setup_practice_disks()
        elif choice == '2':
            self.show_stats()
        elif choice == '3':
            self.network_management()
        elif choice == '4':
            self.reset_machine()
        elif choice == '5':
            self.populate_practice_environment()
        elif choice == '6':
            self.configure_nfs_server()
        elif choice == '7':
            self.link_lab_machine()

    def reset_machine(self):
        """THE single reset. Restores any active faults/preconditions, removes
        every practice artifact (lab files, disks, swap, repos, flatpaks,
        scheduled jobs, autofs, tuned, NFS exports, practice users) and returns
        the box to a clean basic-RHEL state. Preserves the simulator,
        GitHub/SSH connectivity, networking, SELinux and the OS.

        Replaces the old System Reset / Clean lab leftovers / Full System Reset
        trio — one button, one behavior."""
        from core import full_reset
        from utils.helpers import confirm_action

        fmt.clear_screen()
        fmt.print_header("RESET MACHINE")

        print(fmt.warning("This undoes ALL practice changes and returns the machine to a"))
        print(fmt.warning("clean basic-RHEL state. It removes:"))
        print("  - injected faults & task starting-states (restored to original)")
        print("  - all third-party DNF repos (RHEL system repos are kept)")
        print("  - all Flatpak apps and remotes")
        print("  - leftover lab files, practice users/groups, practice disks & swap")
        print("  - scheduled jobs, autofs maps, tuned changes, NFS exports")
        print()
        print(fmt.success("PRESERVED: the rhcsa-simulator, GitHub/SSH auth (gh, ~/.ssh,"))
        print(fmt.success("git config), networking, firewall, SELinux, and the OS itself."))
        print()

        # Show exactly what will go before asking.
        print(fmt.dim("Scanning system..."))
        data = full_reset.preview()
        total = 0
        print()
        print(fmt.bold("Will remove:"))
        for label, items in data.items():
            print(f"  {label}: {len(items)}")
            for it in items[:8]:
                print(fmt.dim(f"      {it}"))
            if len(items) > 8:
                print(fmt.dim(f"      … and {len(items) - 8} more"))
            total += len(items)
        print(fmt.dim("  (plus dnf cache, cron/at jobs, autofs, tuned, NFS exports)"))
        print()

        remove_users = confirm_action(
            "Also delete practice users/groups (UID/GID >= 1000)?", default=True)

        print()
        print(fmt.warning("This is destructive and cannot be undone."))
        confirm = input("Type 'RESET' to proceed (anything else cancels): ").strip()
        if confirm != 'RESET':
            print(fmt.dim("Cancelled — nothing changed."))
            input("\nPress Enter to return...")
            return

        print()
        print(fmt.bold("Resetting machine..."))

        def progress(msg):
            print(msg)

        summary = full_reset.run_all(progress=progress, remove_users=remove_users)

        print()
        print("=" * 50)
        print(fmt.success("Reset complete."))
        print(fmt.info("The box is back to a clean state; simulator and GitHub"))
        print(fmt.info("connectivity were left intact."))
        print()
        input("Press Enter to return...")

    def link_lab_machine(self):
        """Link (or unlink) the second lab machine used by the boot-rescue lab
        and remote tasks. Linking plants this machine's SSH key so everything
        afterwards runs unattended — the key is the only footprint."""
        from core import lab_machine, boot_rescue
        from utils.helpers import confirm_action

        fmt.clear_screen()
        fmt.print_header("LINK SECOND LAB MACHINE")

        existing = lab_machine.load_config()
        if existing:
            adopted = existing.get('adopted_from')
            print(f"Currently linked: {fmt.bold(existing['host'])} "
                  f"(user: {existing.get('user', 'root')})"
                  + (f"  [adopted from the {adopted} config]" if adopted else ""))
            print()
            print("  T. Test the link now (key-based SSH)")
            print("  R. Re-link / change machine")
            print("  X. Unlink")
            print("  0. Back")
            print()
            sub = input("Select: ").strip().lower()
            if sub == 't':
                print(f"\nTesting key-based SSH to {existing['host']}…")
                if lab_machine.key_works():
                    print(fmt.success("OK — unattended SSH works."))
                else:
                    print(fmt.error("Key-based SSH failed. Re-link to run "
                                    "ssh-copy-id again."))
                input("\nPress Enter to return...")
                return
            if sub == 'x':
                if boot_rescue.is_active():
                    print(fmt.warning("\nA boot-rescue scenario is active on this "
                                      "machine — resolve it first (validate or "
                                      "give up)."))
                    input("\nPress Enter to return...")
                    return
                lab_machine.clear_config()
                print(fmt.success("Unlinked."))
                input("\nPress Enter to return...")
                return
            if sub != 'r':
                return
            fmt.clear_screen()
            fmt.print_header("LINK SECOND LAB MACHINE")

        print("The lab machine is a second box on your network that the simulator")
        print("reaches as root over SSH. It powers the Boot Rescue Lab and remote")
        print("tasks, and can be the same VM you use as the NFS server.")
        print()
        print("Linking copies this machine's SSH key over (ssh-copy-id — you'll")
        print("type the root password once). Nothing is installed on the machine.")
        print()
        print(fmt.warning("Use a practice box you control — scenarios MODIFY it."))
        print()

        default_host = ''
        try:
            from core import nfs_server
            nfs_cfg = nfs_server.load_config()
            if nfs_cfg and nfs_cfg.get('host') and not nfs_cfg.get('local'):
                default_host = nfs_cfg['host']
        except Exception:
            pass
        prompt = (f"Lab machine hostname or IP [{default_host}]: " if default_host
                  else "Lab machine hostname or IP: ")
        host = input(prompt).strip() or default_host
        if not host:
            print(fmt.dim("Cancelled."))
            input("\nPress Enter to return...")
            return
        user = input("SSH login user [root]: ").strip() or 'root'

        if not lab_machine.key_works(host=host, user=user):
            print()
            if confirm_action(f"Run ssh-copy-id to {user}@{host} now?", default=True):
                lab_machine.copy_key(host, user)

        print(f"\nVerifying unattended SSH to {user}@{host}…")
        if not lab_machine.key_works(host=host, user=user):
            print(fmt.error("Key-based SSH still fails — not saving the link."))
            print(fmt.dim("Check: root login allowed (PermitRootLogin), the machine "
                          "is reachable, and ssh-copy-id succeeded."))
            input("\nPress Enter to return...")
            return

        lab_machine.save_config(host, user)
        print(fmt.success(f"Linked {user}@{host}. Boot Rescue Lab is ready (menu R)."))
        input("\nPress Enter to return...")

    def configure_nfs_server(self):
        """Provision a real NFS server for the NFS practice tasks — either on
        THIS machine (no second box needed) or on a user-named remote RHEL
        box over SSH — or remove an existing configuration."""
        import getpass
        from core import nfs_server
        from utils.helpers import confirm_action

        fmt.clear_screen()
        fmt.print_header("CONFIGURE NFS SERVER")

        existing = nfs_server.load_config()
        if existing:
            if existing.get('local'):
                print(f"Currently configured: {fmt.bold('this machine (local)')}")
            else:
                saved_pw = 'yes' if existing.get('password') else 'no (key-based)'
                print(f"Currently configured: {fmt.bold(existing['host'])} "
                      f"(user: {existing.get('user', 'root')}, saved password: {saved_pw})")
            print("Exports:")
            for e in existing.get('exports', []):
                print(f"  - {e}")
            print()
            print("  R. Re-provision / change server")
            print("  T. Test connection now (re-provision + showmount)")
            print("  X. Remove config (and tear exports down)")
            print("  0. Back")
            print()
            sub = input("Select: ").strip().lower()
            if sub == 'x':
                print("Removing exports…")
                rok, rout = nfs_server.remove_exports()
                print(fmt.success("Exports removed.") if rok
                      else fmt.warning(f"Could not remove exports (removing local config anyway): {rout[-300:]}"))
                nfs_server.clear_config()
                print(fmt.success("NFS configuration removed. NFS tasks revert to placeholders."))
                input("\nPress Enter to return...")
                return
            if sub == 't':
                print("\nRe-provisioning with saved settings…")
                ok, exports, output = nfs_server.reprovision_from_config()
                host = nfs_server.LOCAL_HOST if existing.get('local') else existing['host']
                if ok:
                    print(fmt.success("OK — exports active:"))
                    for e in exports:
                        print(f"  - {host}:{e}")
                    vok, vout = nfs_server.verify_from_client(host)
                    print(fmt.dim(vout) if vok else fmt.warning(vout))
                else:
                    print(fmt.error("Failed:"))
                    print((output or '')[-1500:])
                input("\nPress Enter to return...")
                return
            if sub not in ('r',):
                return
            fmt.clear_screen()
            fmt.print_header("CONFIGURE NFS SERVER")

        print("NFS tasks need a real NFS server to mount from. Provision one right")
        print("here on this machine — fastest, no second box needed — or point at a")
        print("separate RHEL machine you control over SSH.")
        print()
        print("  L. This machine (local) — installs nfs-utils and exports test data")
        print("     over loopback; tasks mount from localhost")
        print("  R. A remote machine over SSH")
        print("  0. Cancel")
        print()
        mode = input("Select [L]: ").strip().lower() or 'l'
        if mode == '0':
            return
        if mode not in ('l', 'r'):
            print(fmt.dim("Cancelled."))
            input("\nPress Enter to return...")
            return

        if mode == 'l':
            self._configure_local_nfs_server()
            return

        print()
        print("This will SSH into a RHEL machine you specify and set it up as an")
        print("NFS server: install nfs-utils, create and populate exports under")
        print(f"{fmt.bold(nfs_server.EXPORT_BASE)}, write /etc/exports.d, run exportfs,")
        print("enable nfs-server, and open the firewall. Exports are refreshed at the")
        print("start of every exam and torn down afterwards, so each run is clean.")
        print()
        print(fmt.warning("This MODIFIES the remote machine. Use a practice box you control."))
        print()

        host = input("NFS server hostname or IP: ").strip()
        if not host:
            print(fmt.dim("Cancelled."))
            input("\nPress Enter to return...")
            return
        user = input("SSH login user [root]: ").strip() or 'root'

        # Credentials — needed so exams can re-provision unattended.
        password = None
        print()
        print(fmt.bold("Authentication"))
        print("  k. Key-based (run ssh-copy-id now; nothing stored)  [recommended]")
        print("  p. Save a password for unattended re-provisioning")
        auth = input("Choose [k]: ").strip().lower() or 'k'
        if auth == 'p':
            if not nfs_server.sshpass_available():
                print(fmt.warning("sshpass is not installed on this machine; saved-password"))
                print(fmt.warning("auth needs it. Install with: dnf install sshpass"))
                if not confirm_action("Continue and save the password anyway?", default=False):
                    print(fmt.dim("Cancelled.")); input("\nPress Enter to return..."); return
            password = getpass.getpass(f"Password for {user}@{host}: ") or None
            if password:
                print(fmt.dim("Stored locally in /var/lib/rhcsa-simulator/nfs_server.conf (root-only, 0600)."))
        else:
            if confirm_action(f"Run ssh-copy-id to {user}@{host} now?", default=True):
                nfs_server.copy_ssh_key(host, user)

        print()
        if not confirm_action(f"Provision {user}@{host} as an NFS server now?", default=True):
            print(fmt.dim("Cancelled."))
            input("\nPress Enter to return...")
            return

        print()
        print(f"Connecting to {user}@{host}… (enter password/passphrase if prompted)")
        ok, exports, output = nfs_server.provision(host, user, password=password)

        print()
        if not ok:
            print(fmt.error("Provisioning failed:"))
            print((output or "(no output)")[-2000:])
            print()
            print(fmt.dim("Common causes: SSH/root login refused, server has no repo "
                          "access for nfs-utils, or firewall blocking. Fix and retry."))
            input("\nPress Enter to return...")
            return

        print(fmt.success("NFS server provisioned. Exports active:"))
        for e in exports:
            print(f"  - {host}:{e}")

        # Confirm the exports are visible from this client.
        print()
        print("Verifying from this machine (showmount -e)…")
        vok, vout = nfs_server.verify_from_client(host)
        if vok:
            print(fmt.success("showmount sees the exports:"))
            print(fmt.dim(vout))
        else:
            print(fmt.warning(f"Could not confirm via showmount: {vout}"))
            print(fmt.dim("(The server may still be fine — check the firewall on the server.)"))

        nfs_server.save_config(host, user, exports, password=password)
        print()
        print(fmt.success("Saved. NFS tasks will use this server; exports auto-refresh each exam."))
        print(fmt.info(f"Try it: showmount -e {host}  then  mount -t nfs {host}:{exports[0]} /mnt/test"))
        input("\nPress Enter to return...")

    def _configure_local_nfs_server(self):
        """Provision THIS machine as its own NFS server (loopback) — for
        candidates who only have one machine to practice on."""
        from core import nfs_server
        from utils.helpers import confirm_action

        print()
        print("This installs nfs-utils, creates and populates exports under")
        print(f"{fmt.bold(nfs_server.EXPORT_BASE)}, writes /etc/exports.d, runs exportfs,")
        print("enables nfs-server, and opens the firewall — all on THIS machine.")
        print("NFS tasks will then use localhost as the server. Exports refresh at")
        print("the start of every exam and tear down afterwards, so each run is clean.")
        print()
        if not confirm_action("Provision an NFS server on this machine now?", default=True):
            print(fmt.dim("Cancelled."))
            input("\nPress Enter to return...")
            return

        print()
        print("Provisioning…")
        ok, exports, output = nfs_server.provision_local()

        print()
        if not ok:
            print(fmt.error("Provisioning failed:"))
            print((output or "(no output)")[-2000:])
            print()
            print(fmt.dim("Common causes: no repo access for nfs-utils, or the kernel "
                          "NFS server module unavailable. Fix and retry."))
            input("\nPress Enter to return...")
            return

        print(fmt.success("NFS server provisioned. Exports active:"))
        for e in exports:
            print(f"  - {nfs_server.LOCAL_HOST}:{e}")

        print()
        print("Verifying (showmount -e)…")
        vok, vout = nfs_server.verify_from_client(nfs_server.LOCAL_HOST)
        if vok:
            print(fmt.success("showmount sees the exports:"))
            print(fmt.dim(vout))
        else:
            print(fmt.warning(f"Could not confirm via showmount: {vout}"))

        nfs_server.save_config(nfs_server.LOCAL_HOST, None, exports, local=True)
        print()
        print(fmt.success("Saved. NFS tasks will mount from localhost; exports auto-refresh each exam."))
        print(fmt.info(f"Try it: showmount -e localhost  then  mount -t nfs localhost:{exports[0]} /mnt/test"))
        input("\nPress Enter to return...")

    def show_stats(self):
        """Show task statistics, plus review/unflag tasks flagged as bad."""
        from tasks.registry import TaskRegistry
        from core import task_flags

        fmt.clear_screen()
        fmt.print_header("TASK STATISTICS")

        TaskRegistry.initialize()
        TaskRegistry.print_statistics()

        flags = task_flags.all_flags()
        print()
        if flags:
            print(fmt.bold(f"Flagged as bad — marked for potential removal "
                           f"({len(flags)}):"))
            ids = sorted(flags)
            for i, tid in enumerate(ids, 1):
                info = flags[tid] or {}
                reason = info.get('reason', '')
                when = info.get('flagged_at', '')
                print(f"  {i}. {tid}"
                      + (f"  ({when})" if when else ""))
                if reason:
                    print(fmt.dim(f"     {reason}"))
            print(fmt.dim("  Flagged tasks are never offered in any mode."))
            print()
            choice = input("Enter a number to UNFLAG that task, or press "
                           "Enter to return: ").strip()
            if choice.isdigit() and 1 <= int(choice) <= len(ids):
                tid = ids[int(choice) - 1]
                task_flags.unflag(tid)
                print(fmt.success(f"Unflagged '{tid}' — back in rotation."))
                input("\nPress Enter to return...")
        else:
            print(fmt.dim("No tasks are flagged as bad. (Flag one with 'b' after "
                          "a practice task or from Result History.)"))
            input("\nPress Enter to return...")

    def export_report(self):
        """Export progress report."""
        from core.results_db import get_results_db

        fmt.clear_screen()
        fmt.print_header("EXPORT REPORT")

        db = get_results_db()

        # Generate a text report from ResultsDB
        print("Generating progress report...")
        print()

        exam_count = db.get_exam_count()
        practice_count = db.get_practice_count()
        recent = db.get_recent_exams(10)
        all_stats = db.get_all_category_stats()
        weak = db.get_weak_categories(0.7)

        # Build report
        lines = []
        lines.append(f"{settings.APP_NAME} v{settings.VERSION} - Progress Report")
        lines.append("=" * 60)
        lines.append("")
        lines.append(f"Exams Taken: {exam_count}")
        lines.append(f"Practice Attempts: {practice_count}")
        lines.append(f"Categories Practiced: {len(all_stats)}")
        lines.append("")

        if recent:
            lines.append("Recent Exams:")
            for r in recent:
                date = r['start_time'][:10] if r['start_time'] else "Unknown"
                status = "PASS" if r['passed'] else "FAIL"
                lines.append(f"  {date} - {r['percentage']:.0f}% {status}")
            lines.append("")

        if all_stats:
            lines.append("Category Performance:")
            for s in all_stats:
                rate = s['success_rate'] * 100
                lines.append(f"  {s['category']}: {rate:.0f}% ({s['attempts']} attempts)")
            lines.append("")

        if weak:
            lines.append("Weak Areas:")
            for w in weak:
                rate = w['success_rate'] * 100
                lines.append(f"  {w['category']}: {rate:.0f}%")
            lines.append("")

        report_text = "\n".join(lines)

        # Save to file
        report_path = settings.DATA_DIR / "progress_report.txt"
        try:
            with open(report_path, 'w') as f:
                f.write(report_text)
            print(fmt.success(f"Report saved to: {report_path}"))
        except Exception as e:
            print(fmt.error(f"Error saving report: {e}"))
            print()
            print("Report content:")
            print(report_text)

        print()
        input("Press Enter to return...")

    def progress_snapshot(self):
        """Backup/restore task history via a portable code, and prune entries.

        Designed for snapshot/reinstall workflows: export a code, keep it
        somewhere, then import it on a fresh box — no login, no server."""
        from core import progress_code
        from core.results_db import get_results_db
        from utils.helpers import confirm_action

        db = get_results_db()

        while True:
            fmt.clear_screen()
            fmt.print_header("PROGRESS SNAPSHOT")
            print(f"  Exams recorded: {db.get_exam_count()}")
            print(f"  Practice/adaptive attempts: {db.get_practice_count()}")
            print(f"  Categories with SM-2 state: {len(db.get_all_category_stats())}")
            print()
            print("A snapshot code carries your history + adaptive state across")
            print("reinstalls and VM reverts. Save it somewhere safe (there is")
            print("no login/server backup).")
            print()
            print(fmt.dim(f"An autosave code is also written to {progress_code.AUTOSAVE_PATH}"))
            print(fmt.dim("after every recorded result; if it ever holds more history than"))
            print(fmt.dim("this install (e.g. after a reinstall), the simulator offers to"))
            print(fmt.dim("import it at launch."))
            print()
            print(fmt.bold("Options"))
            print("  1. Export a progress code (backup)")
            print("  2. Import a progress code (restore)")
            print("  3. Prune history (remove entries)")
            print("  0. Back")
            print()
            choice = input("Select option: ").strip()

            if choice == '1':
                self._snapshot_export(progress_code, db)
            elif choice == '2':
                self._snapshot_import(progress_code, db, confirm_action)
            elif choice == '3':
                self._snapshot_prune(db, confirm_action)
            elif choice == '0' or choice == '':
                return

    def _snapshot_export(self, progress_code, db):
        fmt.clear_screen()
        fmt.print_header("EXPORT PROGRESS CODE")
        try:
            code = progress_code.export_code(db)
        except Exception as e:
            print(fmt.error(f"Could not export: {e}"))
            input("\nPress Enter to return...")
            return

        wrapped_code = textwrap.fill(code, width=80)

        print("Copy this code and keep it safe — import it on any new install:")
        print()
        print(wrapped_code)
        print()

        try:
            path = settings.DATA_DIR / "progress_code.txt"
            with open(path, 'w') as f:
                f.write(wrapped_code + "\n")
            print(fmt.dim(f"Also saved to {path} ({len(code)} chars)."))
        except Exception:
            pass
        input("\nPress Enter to return...")

    def _snapshot_import(self, progress_code, db, confirm_action):
        fmt.clear_screen()
        fmt.print_header("IMPORT PROGRESS CODE")
        print("Paste your progress code (dashes/spaces/newlines are fine).")
        print(fmt.dim("Enter a blank line when done, or just press Enter to cancel."))
        print()
        lines = []
        while True:
            line = input()
            if not line.strip():
                break
            lines.append(line.strip())
        code = ''.join(lines)
        if not code:
            print(fmt.dim("Cancelled."))
            input("\nPress Enter to return...")
            return

        # Validate + preview before touching the DB.
        try:
            payload = progress_code.decode(code)
        except progress_code.ProgressCodeError as e:
            print(fmt.error(f"Invalid code: {e}"))
            input("\nPress Enter to return...")
            return

        summary = progress_code.summarize(payload)
        print()
        print(fmt.bold("This code contains:"))
        for k, v in summary.items():
            print(f"  {k}: {v}")
        print()

        has_local = db.get_exam_count() > 0 or db.get_practice_count() > 0
        mode = 'replace'
        if has_local:
            print(fmt.warning("You already have progress on this install."))
            print("  R - Replace (wipe local history, then restore the code) [recommended for a fresh box]")
            print("  M - Merge (keep local history, add the code's entries, skip duplicates)")
            print("  C - Cancel")
            sel = input("Choose [R]: ").strip().lower() or 'r'
            if sel == 'c':
                print(fmt.dim("Cancelled."))
                input("\nPress Enter to return...")
                return
            mode = 'merge' if sel == 'm' else 'replace'
            if mode == 'replace' and not confirm_action(
                    "Really wipe local history and replace it?", default=False):
                print(fmt.dim("Cancelled."))
                input("\nPress Enter to return...")
                return

        counts = db.load_progress(payload, mode=mode)
        print()
        print(fmt.success(f"Imported ({mode}): "
                          f"{counts['exams']} exams, {counts['tasks']} exam tasks, "
                          f"{counts['practice']} attempts, {counts['weak']} categories."))
        input("\nPress Enter to return...")

    def _snapshot_prune(self, db, confirm_action):
        while True:
            fmt.clear_screen()
            fmt.print_header("PRUNE HISTORY")
            print(fmt.bold("Remove:"))
            print("  1. A specific exam")
            print("  2. Recent practice attempts (pick which — e.g. a botched session)")
            print("  3. All practice/adaptive attempts")
            print("  4. Reset one category's adaptive (SM-2) state")
            print("  5. Everything (wipe all progress)")
            print("  0. Back")
            print()
            print(fmt.dim("Weak-area/SM-2 stats are recomputed from the surviving history"))
            print(fmt.dim("after every prune, so removed attempts stop counting against you."))
            print()
            choice = input("Select option: ").strip()

            if choice == '1':
                exams = db.list_exams()
                if not exams:
                    print(fmt.dim("No exams recorded."))
                    input("\nPress Enter...")
                    continue
                print()
                for i, e in enumerate(exams, 1):
                    date = (e['start_time'] or '')[:16]
                    status = 'PASS' if e['passed'] else 'FAIL'
                    print(f"  {i:2d}. {date}  {e['percentage']:.0f}% {status}  "
                          f"({e['mode']})  {e['exam_id']}")
                print()
                sel = input("Number to delete (blank to cancel): ").strip()
                if sel.isdigit() and 1 <= int(sel) <= len(exams):
                    ex = exams[int(sel) - 1]
                    if confirm_action(f"Delete exam {ex['exam_id']}?", default=False):
                        db.delete_exam(ex['exam_id'])
                        print(fmt.success("Deleted."))
                        input("\nPress Enter...")
            elif choice == '2':
                attempts = db.list_recent_practice(limit=30)
                if not attempts:
                    print(fmt.dim("No practice attempts recorded."))
                    input("\nPress Enter...")
                    continue
                print()
                for i, a in enumerate(attempts, 1):
                    status = 'PASS' if a['passed'] else 'FAIL'
                    print(f"  {i:2d}. {(a['created_at'] or '')[:16]}  "
                          f"{a['score']}/{a['max_score']} {status}  "
                          f"{a['category']}  {a['task_id']}  ({a['mode']})")
                print()
                sel = input("Numbers to delete (e.g. 1,3 or 1-5; blank to cancel): ").strip()
                picked = set()
                for part in sel.split(','):
                    part = part.strip()
                    if '-' in part:
                        lo, _, hi = part.partition('-')
                        if lo.strip().isdigit() and hi.strip().isdigit():
                            picked.update(range(int(lo), int(hi) + 1))
                    elif part.isdigit():
                        picked.add(int(part))
                ids = [attempts[i - 1]['id'] for i in sorted(picked)
                       if 1 <= i <= len(attempts)]
                if ids and confirm_action(f"Delete {len(ids)} attempt(s)?",
                                          default=False):
                    n = db.delete_practice_attempts(ids)
                    db.rebuild_weak_areas()
                    print(fmt.success(f"Removed {n} attempt(s); weak areas recomputed."))
                    input("\nPress Enter...")
                elif not ids:
                    print(fmt.dim("Nothing selected."))
                    input("\nPress Enter...")
            elif choice == '3':
                if confirm_action("Delete ALL practice/adaptive attempts?", default=False):
                    n = db.clear_practice_history()
                    db.rebuild_weak_areas()
                    print(fmt.success(f"Removed {n} attempt(s); weak areas recomputed."))
                    input("\nPress Enter...")
            elif choice == '4':
                stats = db.get_all_category_stats()
                if not stats:
                    print(fmt.dim("No category state recorded."))
                    input("\nPress Enter...")
                    continue
                print()
                for i, s in enumerate(stats, 1):
                    print(f"  {i:2d}. {s['category']} "
                          f"({s['success_rate'] * 100:.0f}%, {s['attempts']} attempts)")
                print()
                sel = input("Number to reset (blank to cancel): ").strip()
                if sel.isdigit() and 1 <= int(sel) <= len(stats):
                    cat = stats[int(sel) - 1]['category']
                    if confirm_action(f"Reset SM-2 state for '{cat}'?", default=False):
                        db.reset_category(cat)
                        print(fmt.success("Reset."))
                        input("\nPress Enter...")
            elif choice == '5':
                print(fmt.warning("This wipes ALL exams, attempts, and adaptive state."))
                if confirm_action("Type-safe confirm: wipe everything?", default=False):
                    db.clear_all_progress()
                    print(fmt.success("All progress cleared."))
                    input("\nPress Enter...")
            elif choice == '0' or choice == '':
                return

    def setup_practice_disks(self):
        """Set up or manage practice disks for LVM/partition tasks."""
        from utils.helpers import (
            get_loop_devices, create_practice_devices, cleanup_practice_devices,
            get_practice_device_config, save_practice_device_config,
            list_all_block_devices, confirm_action
        )

        fmt.clear_screen()
        fmt.print_header("PRACTICE DISK SETUP")

        # Show current config
        cfg = get_practice_device_config()
        loop_devices = get_loop_devices()

        print(fmt.bold("Current Configuration:"))
        if cfg:
            mode_label = "Loop devices" if cfg['mode'] == 'loop' else "Real disk(s)"
            print(f"  Mode: {mode_label}")
            print(f"  Devices: {', '.join(cfg['devices']) if cfg['devices'] else 'none'}")
        else:
            print("  Not configured")
        if loop_devices:
            print(f"  Attached loop devices: {', '.join(loop_devices)}")
        print()

        print(fmt.bold("Options:"))
        print("  1. Create loop devices  (3 x 500MB virtual disks — no spare drive needed)")
        print("  2. Use a real disk      (pick a spare drive already in your VM)")
        print("  3. Custom loop devices  (choose count and size)")
        print("  4. Clean up / reset     (remove LVM structures from practice devices)")
        print("  0. Return")
        print()

        choice = input("Select option: ").strip()

        if choice == '1':
            print()
            print("Creating 3 x 500MB loop devices...")
            devices = create_practice_devices(count=3, size_mb=500)
            if devices:
                save_practice_device_config('loop', devices)
                print(fmt.success(f"Ready: {', '.join(devices)}"))
                print(fmt.info(f"  {devices[-1]} is reserved for swap/partition practice"))
            else:
                print(fmt.error("Failed to create loop devices"))

        elif choice == '2':
            self._select_real_disk(list_all_block_devices, save_practice_device_config)

        elif choice == '3':
            try:
                count = int(input("Number of disks [3]: ").strip() or '3')
                size = int(input("Size per disk in MB [500]: ").strip() or '500')
                print()
                devices = create_practice_devices(count=count, size_mb=size)
                if devices:
                    save_practice_device_config('loop', devices)
                    print(fmt.success(f"Ready: {', '.join(devices)}"))
                else:
                    print(fmt.error("Failed to create loop devices"))
            except ValueError:
                print(fmt.error("Invalid input"))

        elif choice == '4':
            print()
            mode_desc = "real disk(s)" if cfg and cfg['mode'] == 'real' else "loop devices"
            print(fmt.warning(f"This removes all LVM/swap structures from practice {mode_desc}."))
            if cfg and cfg['mode'] == 'real':
                print(fmt.warning("Partition tables on real disks are NOT touched."))
            if confirm_action("Continue?", default=False):
                if cleanup_practice_devices():
                    print(fmt.success("Practice devices cleaned up"))
                else:
                    print(fmt.error("Cleanup failed — check manually"))

        print()
        input("Press Enter to return...")

    def _select_real_disk(self, list_all_block_devices, save_practice_device_config):
        """Interactive picker for selecting real disks as practice devices."""
        from utils.helpers import wipe_disk

        print()
        print("Scanning block devices...")
        all_devs = list_all_block_devices()

        safe = [d for d in all_devs if not d['is_system'] and not d['mounted']]
        risky = [d for d in all_devs if d['is_system'] or d['mounted']]

        if not safe and not risky:
            print(fmt.error("No block devices found."))
            return

        print()
        if safe:
            print(fmt.bold("Available disks:"))
            for i, d in enumerate(safe, 1):
                notes = []
                if d['has_partitions']:
                    notes.append("has partitions — will be wiped")
                if d.get('has_swap'):
                    notes.append("swap active — will be deactivated")
                note_str = f"  ({', '.join(notes)})" if notes else "  (empty)"
                print(f"  {i}. {d['device']}  {d['size']}{note_str}")
        else:
            print(fmt.warning("No spare disks found."))

        if risky:
            print()
            print(fmt.dim("Blocked (system disk or has active mounts — cannot select):"))
            for d in risky:
                flag = "SYSTEM DISK" if d['is_system'] else "has active mounts"
                print(fmt.dim(f"      {d['device']}  {d['size']}  [{flag}]"))

        if not safe:
            return

        print()
        print("Enter one or more numbers separated by spaces (e.g. '1 2'),")
        print("or full device paths (e.g. '/dev/sda /dev/sdb'):")
        raw = input("> ").strip()
        if not raw:
            return

        # Resolve selections
        chosen = []
        system_names = {d['device'] for d in all_devs if d['is_system']}
        for token in raw.split():
            if token.startswith('/dev/'):
                dev = token
            else:
                try:
                    idx = int(token) - 1
                    if not (0 <= idx < len(safe)):
                        print(fmt.error(f"Invalid number: {token}"))
                        return
                    dev = safe[idx]['device']
                except ValueError:
                    print(fmt.error(f"Invalid input: {token}"))
                    return
            if dev in system_names:
                print(fmt.error(f"BLOCKED: {dev} is the system disk. Aborting."))
                return
            if dev not in chosen:
                chosen.append(dev)

        if not chosen:
            return

        print()
        print(fmt.error("!" * 60))
        print(fmt.error("  WARNING — DESTRUCTIVE OPERATION — THIS CANNOT BE UNDONE"))
        print(fmt.error("!" * 60))
        print()
        print("The following disks will be COMPLETELY WIPED:")
        for dev in chosen:
            info = next((d for d in all_devs if d['device'] == dev), {})
            print(fmt.error(f"    {dev}  {info.get('size', '?')}"))
        print()
        print("  • ALL PARTITIONS will be deleted")
        print("  • ALL DATA will be permanently destroyed")
        print("  • Partition tables will be zeroed out")
        print("  • Disks will be left as raw unpartitioned block devices")
        print()

        confirm1 = input("Type YES (all caps) to continue: ").strip()
        if confirm1 != 'YES':
            print("Cancelled.")
            return

        expected = ' '.join(chosen)
        confirm2 = input(f"Type the device path(s) exactly to confirm [{expected}]: ").strip()
        if confirm2 != expected:
            print("Confirmation did not match. Cancelled.")
            return

        print()
        for dev in chosen:
            print(f"Wiping {dev}...")
            ok, msgs = wipe_disk(dev)
            for msg in msgs:
                print(f"  {msg}")
            print()

        save_practice_device_config('real', chosen)
        print(fmt.success(f"Done. Practice disks: {', '.join(chosen)}"))
        print(fmt.info("Disks are raw and ready. LVM/partition tasks will use them directly."))

    def network_management(self):
        """Network backup and restore management."""
        try:
            from device import get_network_manager
        except ImportError:
            print(fmt.warning("Network management module not available."))
            input("Press Enter to return...")
            return

        from utils.helpers import confirm_action

        nm = get_network_manager()

        fmt.clear_screen()
        fmt.print_header("NETWORK BACKUP/RESTORE")

        # Show current state
        print(fmt.bold("Current Network State:"))
        try:
            print(f"  Primary Interface: {nm.get_primary_interface() or 'Unknown'}")
            print(f"  Primary IP: {nm.get_primary_ip() or 'Unknown'}")
        except Exception:
            print("  (Could not detect network state)")
        print()

        print(fmt.warning("WARNING: Network practice can disconnect SSH!"))
        print(fmt.dim("Always backup before practicing networking tasks."))
        print()

        # List existing backups
        try:
            backups = nm.list_backups()
        except Exception:
            backups = []

        if backups:
            print(fmt.bold(f"Available Backups ({len(backups)}):"))
            for i, b in enumerate(backups[:5], 1):
                print(f"  {i}. {b['timestamp'][:19]} - {b['hostname']} ({b['primary_ip']})")
        else:
            print(fmt.dim("No backups found."))
        print()

        print(fmt.bold("Options:"))
        print("  1. Backup Current State")
        print("  2. Show Recovery Commands")
        print("  3. Cleanup Practice Connections")
        print("  4. Full Restore from Backup")
        print("  0. Return to Setup")
        print()

        choice = input("Select option: ").strip()

        if choice == '1':
            print()
            print("Backing up network state...")
            filepath = nm.backup_state("manual")
            print(fmt.success("Backup saved!"))
            print(f"  Location: {filepath}")
            print()
            nm.print_recovery_commands()

        elif choice == '2':
            nm.print_recovery_commands()

        elif choice == '3':
            print()
            print("This will remove connections matching: lab-*, test-*, practice-*, team0, team1")
            if confirm_action("Proceed with cleanup?", default=True):
                removed = nm.cleanup_practice_connections()
                if removed:
                    print(fmt.success(f"Removed {len(removed)} connections:"))
                    for conn in removed:
                        print(f"  - {conn}")
                else:
                    print(fmt.info("No practice connections found to remove."))

        elif choice == '4':
            if not backups:
                print(fmt.error("No backups available!"))
            else:
                print()
                print("Available backups:")
                for i, b in enumerate(backups[:5], 1):
                    print(f"  {i}. {b['timestamp'][:19]} - {b['hostname']}")
                print()
                sel = input("Select backup number [1]: ").strip() or '1'
                try:
                    idx = int(sel) - 1
                    if 0 <= idx < len(backups):
                        if confirm_action("This will restore network settings. Continue?", default=False):
                            print()
                            print("Restoring network state...")
                            result = nm.full_cleanup(backups[idx]['file'])
                            if 'error' in result:
                                print(fmt.error(result['error']))
                            else:
                                print(fmt.success("Cleanup complete!"))
                                if result.get('connections_removed'):
                                    print(f"  Removed connections: {', '.join(result['connections_removed'])}")
                                if result.get('hostname_restored'):
                                    print("  Hostname restored")
                    else:
                        print(fmt.error("Invalid selection"))
                except ValueError:
                    print(fmt.error("Invalid input"))

        print()
        input("Press Enter to return...")

    def show_result_history(self):
        """List recent exam results and allow drilling into task-level detail."""
        import json
        from core.results_db import get_results_db

        db = get_results_db()

        while True:
            fmt.clear_screen()
            fmt.print_header("RESULT HISTORY")

            exams = db.get_recent_exams(10)

            if not exams:
                print(fmt.info("No exam results yet. Complete a mock exam to see results here."))
                print()
                input("Press Enter to return...")
                return

            print(fmt.bold(f"Last {len(exams)} exam sessions:"))
            print()
            for i, ex in enumerate(exams, 1):
                date = ex['start_time'][:16].replace('T', ' ') if ex['start_time'] else '?'
                pct = ex['percentage']
                status = fmt.success("PASS") if ex['passed'] else fmt.error("FAIL")
                tasks = ex.get('task_count', '?')
                score = f"{ex['total_score']}/{ex['max_score']}"
                print(f"  {i:2}. {date}  {score} pts  {pct:.0f}%  {status}  ({tasks} tasks)")

            print()
            print(fmt.dim("  0. Return to menu"))
            print()

            choice = input("Select a session to review (number): ").strip()
            if choice == '0' or choice.lower() == 'q':
                return

            try:
                idx = int(choice) - 1
                if not (0 <= idx < len(exams)):
                    print(fmt.error("Invalid selection"))
                    input("Press Enter to continue...")
                    continue
            except ValueError:
                print(fmt.error("Please enter a number"))
                input("Press Enter to continue...")
                continue

            self._show_exam_detail(db, exams[idx])

    def _show_exam_detail(self, db, exam):
        """Show per-task breakdown for one exam session."""
        import json
        from config import settings

        exam_id = exam['exam_id']
        task_results = db.get_exam_task_results(exam_id)

        if not task_results:
            print(fmt.info("No per-task data saved for this session."))
            print(fmt.dim("(Per-task detail is saved starting from sessions after this update)"))
            input("\nPress Enter to return...")
            return

        task_list = list(enumerate(task_results, 1))

        while True:
            fmt.clear_screen()
            date = exam['start_time'][:16].replace('T', ' ') if exam['start_time'] else '?'
            pct = exam['percentage']
            status = fmt.success("PASS") if exam['passed'] else fmt.error("FAIL")
            fmt.print_header(f"EXAM DETAIL — {date}")
            print(f"  Result: {status}  {exam['total_score']}/{exam['max_score']} pts  ({pct:.0f}%)")
            print()

            for num, tr in task_list:
                icon = fmt.success("✓") if tr['passed'] else fmt.error("✗")
                cat = fmt.format_category_name(tr['category'])
                domain = settings.EXAM_DOMAINS.get(tr.get('domain', 0), '')
                score_str = f"{tr['score']}/{tr['max_score']}pt"
                # Show first line of description only
                first_line = tr['description'].splitlines()[0] if tr['description'] else tr['task_id']
                print(f"  {num:2}. {icon} [{score_str:>8}]  {first_line[:55]}")
                if domain:
                    d_num = tr.get('domain', '?')
                    print(f"       {fmt.dim(f'D{d_num} {domain} — {cat}')}")

            print()
            print(fmt.dim("  Enter task number for full detail, 0 to go back"))
            print()

            choice = input("Select task: ").strip()
            if choice == '0' or choice.lower() == 'q':
                return

            try:
                tidx = int(choice) - 1
                if not (0 <= tidx < len(task_list)):
                    continue
            except ValueError:
                continue

            self._show_task_detail(task_list[tidx][1])

    def _show_task_detail(self, tr):
        """Show full detail for one task result including failed checks and hints.

        The (often long) static detail is rendered through a pager so it is
        scrollable; the interactive dispute prompt runs afterwards."""
        import io
        import json
        from contextlib import redirect_stdout

        fmt.clear_screen()

        # Parse checks once (also used by the dispute prompt below).
        checks = []
        if tr.get('checks_json'):
            try:
                checks = json.loads(tr['checks_json'])
            except Exception:
                pass

        buf = io.StringIO()
        with redirect_stdout(buf):
            status = fmt.success("PASSED") if tr['passed'] else fmt.error("FAILED")
            cat = fmt.format_category_name(tr['category'])
            print(f"{status}  {tr['score']}/{tr['max_score']} points  [{cat} / {tr['difficulty']}]")
            print("=" * 60)
            print()

            # Task description (what was asked)
            print(fmt.bold("Task:"))
            print(tr['description'] or "(no description saved)")
            print()

            # Validation checks (what the system found)
            if checks:
                print(fmt.bold("Validation breakdown:"))
                for c in checks:
                    icon = fmt.success("✓") if c.get('passed') else fmt.error("✗")
                    pts = c.get('points', 0)
                    max_pts = c.get('max_points', pts)
                    msg = c.get('message', c.get('name', ''))
                    print(f"  {icon} [{pts}/{max_pts}pt]  {msg}")
                print()

            # Hints / what to study (only if task failed)
            if not tr['passed']:
                hints = []
                if tr.get('hints_json'):
                    try:
                        hints = json.loads(tr['hints_json'])
                    except Exception:
                        pass

                exam_tips = []
                if tr.get('exam_tips_json'):
                    try:
                        exam_tips = json.loads(tr['exam_tips_json'])
                    except Exception:
                        pass

                if hints:
                    print(fmt.bold("What to study / how to fix it:"))
                    for h in hints:
                        print(f"  • {h}")
                    print()

                if exam_tips:
                    print(fmt.bold("Exam tips:"))
                    for t in exam_tips:
                        print(f"  * {t}")
                    print()

                if not hints and not exam_tips:
                    print(fmt.dim("(No hints saved for this session — re-run a new exam to get hints)"))
                    print()

        fmt.page_output(buf.getvalue())

        # Offer the dispute path when there are checks to dispute, and let a
        # bad question be flagged out of rotation from here too.
        if checks:
            print(fmt.dim("Think the checker got this wrong? Type 'd' to dispute it "
                          "(opens a GitHub issue; an AI reviews your evidence and "
                          "pushes a fix if you're right)."))
        print(fmt.dim("Type 'b' to flag this task as bad (marked for potential "
                      "removal — never offered again)."))
        choice = input("Press Enter to return to session view"
                       + (", 'd' to dispute" if checks else "")
                       + ", or 'b' to flag: ").strip().lower()
        if choice == 'd' and checks:
            self._dispute_check_flow(tr, checks)
        elif choice == 'b':
            from core import task_flags
            reason = input("Why is it bad? (optional): ").strip()
            if task_flags.flag(tr.get('task_id', ''), reason):
                print(fmt.success(f"Flagged '{tr.get('task_id')}' — it won't be "
                                  "offered again (unflag in Setup → Task "
                                  "Statistics)."))
            else:
                print(fmt.dim("Already flagged."))
            input("\nPress Enter to return...")

    def _dispute_check_flow(self, tr, checks):
        """Let the candidate dispute a checker result: capture system-state
        evidence + their argument and open a GitHub issue that triggers an AI
        review (which pushes a fix PR if the checker is genuinely wrong)."""
        from core import dispute
        from utils.helpers import confirm_action

        fmt.clear_screen()
        print(fmt.bold("DISPUTE A CHECKER RESULT"))
        print("=" * 60)
        print()
        print("If you believe the checker scored this task incorrectly, you can")
        print("dispute it. Here is exactly what happens when you do:")
        print()
        print("  1. Your written argument and the relevant LIVE system state")
        print("     (command output) are captured as evidence.")
        print("  2. A GitHub issue is opened on this project containing that")
        print("     evidence (so review it for anything sensitive first).")
        print("  3. An AI reviewer inspects the validator for this task, compares")
        print("     it against your evidence, and comments a verdict.")
        print("  4. If the checker is wrong, it opens a fix PR automatically.")
        print()
        print(fmt.warning("Evidence (file paths, hostnames, command output) becomes public on GitHub."))
        print()

        if not confirm_action("Open a GitHub dispute for this task?", default=False):
            print(fmt.dim("Cancelled — nothing was sent."))
            input("\nPress Enter to return to session view...")
            return

        # 1. Which checks are being disputed (default: the failed ones).
        print()
        print(fmt.bold("Which check(s) are wrong?"))
        for i, c in enumerate(checks, 1):
            mark = fmt.success("✓") if c.get('passed') else fmt.error("✗")
            print(f"  {i}. {mark} {c.get('message', c.get('name', ''))}")
        print()
        sel = input("Enter numbers (comma-separated), or Enter for all FAILED checks: ").strip()
        if sel:
            disputed = []
            for tok in sel.replace(',', ' ').split():
                try:
                    idx = int(tok) - 1
                    if 0 <= idx < len(checks):
                        disputed.append(checks[idx])
                except ValueError:
                    pass
        else:
            disputed = [c for c in checks if not c.get('passed')]
        if not disputed:
            disputed = list(checks)

        # 2. The candidate's argument.
        print()
        print(fmt.bold("Why is the checker wrong? (explain your evidence)"))
        print(fmt.dim("Enter your argument; finish with an empty line."))
        arg_lines = []
        while True:
            line = input("  ")
            if line == '' and arg_lines:
                break
            if line == '' and not arg_lines:
                continue
            arg_lines.append(line)
        argument = "\n".join(arg_lines)

        # 3. Optional extra evidence commands.
        print()
        print(fmt.bold("Extra evidence commands (optional)"))
        print(fmt.dim("Type read-only commands whose output proves your point, one per"))
        print(fmt.dim("line (e.g. 'blkid /dev/sda1'). Finish with an empty line."))
        extra_cmds = []
        while True:
            line = input("  $ ").strip()
            if line == '':
                break
            extra_cmds.append(line)

        # 4. Capture evidence + build + save the report.
        print()
        print("Capturing system state…")
        evidence = dispute.collect_evidence(tr.get('category', ''), extra_cmds)
        body = dispute.build_report(tr, disputed, argument, evidence)
        path = dispute.save_report(tr, body)
        print(fmt.success(f"Saved dispute report: {path}"))

        # 5. Submit via gh (or fall back to a no-auth browser URL).
        if not dispute.gh_available():
            print()
            print(fmt.warning("GitHub CLI ('gh') isn't installed/authenticated on this host, so"))
            print(fmt.warning("the issue can't be opened automatically from here."))
            self._offer_manual_dispute(dispute, tr, path, body)
            input("\nPress Enter to return to session view...")
            return

        print()
        if not confirm_action("Open the GitHub issue now?", default=True):
            print(fmt.dim(f"Not sent. Report kept at {path}."))
            self._offer_manual_dispute(dispute, tr, path, body)
            input("\nPress Enter to return to session view...")
            return

        ok, info = dispute.submit_issue(tr, path)
        print()
        if ok:
            print(fmt.success("Dispute filed!"))
            if info:
                print(f"  {info}")
            print(fmt.info("An AI reviewer will inspect the validator and, if the checker is"))
            print(fmt.info("wrong, open a fix PR. Watch the issue for its verdict."))
        else:
            print(fmt.error(f"Could not open the issue via gh: {info}"))
            self._offer_manual_dispute(dispute, tr, path, body)
        input("\nPress Enter to return to session view...")

    def _offer_manual_dispute(self, dispute, tr, path, body):
        """Show no-auth ways to file the dispute when gh can't do it here:
        a pre-filled browser URL (open on any machine logged into GitHub) plus
        the exact gh command, with the full report kept locally either way."""
        print()
        print(fmt.bold("File it without gh — open this URL in any browser where you're"))
        print(fmt.bold("logged into GitHub, then click 'Submit new issue':"))
        print()
        try:
            print(dispute.issue_url(tr, body))
        except Exception:
            print(fmt.dim("  (could not build issue URL)"))
        print()
        print(fmt.dim("The label is pre-set, so the AI reviewer triggers automatically."))
        print(fmt.dim(f"Full report saved locally: {path}"))
        print(fmt.dim("Or, on a host with gh authenticated:"))
        print(fmt.dim(f"  gh issue create --repo {dispute.repo_slug()} "
                      f"--label {dispute.DISPUTE_LABEL} "
                      f"--title '[checker dispute] {tr.get('task_id')}' --body-file {path}"))

    def populate_practice_environment(self):
        """Install/remove lightweight packages to build up DNF transaction history."""
        from utils.helpers import populate_dnf_history, confirm_action

        fmt.clear_screen()
        fmt.print_header("POPULATE PRACTICE ENVIRONMENT")

        print("This will install and immediately remove a series of small packages")
        print("to build up DNF transaction history for practice tasks.")
        print()
        print(fmt.info("Only packages NOT already installed will be touched."))
        print(fmt.info("Nothing on your system will be permanently changed."))
        print(fmt.warning("Requires active DNF repos and internet/local mirror access."))
        print(fmt.warning("Takes 2–5 minutes depending on connection speed."))
        print()

        if not confirm_action("Build DNF transaction history?", default=True):
            print(fmt.dim("Cancelled."))
            print()
            input("Press Enter to return...")
            return

        print()
        print("Working... (this may take a few minutes)")
        print()

        def progress(msg):
            print(f"  {msg}")

        cycles = populate_dnf_history(target_transactions=12, progress_callback=progress)

        print()
        if cycles > 0:
            print(fmt.success(f"Done! Completed {cycles} install/remove cycles ({cycles * 2} new DNF transactions)."))
            print(fmt.info("Run 'dnf history' to verify."))
        else:
            print(fmt.error("No cycles completed — repos may not be configured or packages unavailable."))
            print(fmt.dim("Make sure DNF repos are set up: dnf repolist"))

        print()
        input("Press Enter to return...")

