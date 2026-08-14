# RHCSA Mock Exam Simulator


A command-line **RHCSA EX200 v10** (Red Hat Enterprise Linux 10) exam simulator.
It generates tasks, sets up each task's starting state, validates your real
system configuration with safe read-only checks, and tracks progress over time.

> **188 tasks · 25 categories · 8 domains**, aligned to EX200 v10 — including
> Flatpak, systemd timers, `tuned-adm`, and secure file transfer (no legacy
> module streams).
>
> **Active development** — useful for prep, but expect rough edges. Bug reports
> and contributions welcome.

---
## RHCE Simulator now available
Smashed your RHCSA exam and looking for the next step? Check out https://github.com/TroggoMan/rhce-simulator for Ansible prep and get your RHCE going!

---
## Quick Start

```bash
# On a RHEL 10 / Rocky 10 / Alma 10 VM, as root:
sudo -i
git clone https://github.com/justbest23/rhcsa-simulator.git
cd rhcsa-simulator
./install.sh                 # interactive (use --yes for unattended)
rhcsa-simulator --exam       # mock exam — task panel opens in its own window
```

The exam prints a URL at start; open it beside your terminals. On the real
EX200 the questions are **not in your terminal** — they live in a separate
window on the exam desktop, and working that window while you work the box is
a skill in itself. The panel reproduces it: a collapsed checklist of tasks,
each opening in place to reveal its text, **Revisit** and **Done** ticks on
every row, and the countdown beside them.
See [Exam task panel](#exam-task-panel--the-closest-thing-to-the-real-exam).

<p align="center">
  <img src="docs/img/task-panel.jpg" alt="The exam task panel: a collapsed list of tasks with Revisit and Done ticks, one row expanded to show its text, and a countdown in the sidebar" width="900">
</p>

Prefer to keep everything in the terminal, or on a box with no browser
anywhere? `--no-gui` turns the panel off and everything still works — as does
`rhcsa-simulator` on its own, which opens the menu, where **E** is a full Mock
Exam and **Q** a quick practice round.

The simulator **auto-creates the practice disks it needs** (loop devices, plus
any spare disk like `/dev/sda`) and **sets up each task's starting state** at
exam start — so a "kill the apache processes" task actually has processes
running, and an "extend the logical volume" task actually has a volume. After
the exam the environment is kept for review/disputes; **Setup → Reset Machine**
(or the next session start) cleans everything up.

**Typical loop:** read a task → do it on the system in another terminal → return
and press Enter to validate → review per-check feedback and score.

---

## Requirements

| | Minimum |
|---|---|
| **OS** | RHEL 10, Rocky Linux 9/10, or AlmaLinux 9/10 (EX200 v10 targets RHEL 10) |
| **Python** | 3.6+ (ships with the OS) |
| **Privileges** | root (validation reads users, services, mounts, SELinux, etc.) |
| **Dependencies** | none — Python standard library only |
| **Disk** | a few hundred MB free under `/var/lib/rhcsa-simulator` for loop-device images |
| **Network** | not required (optional, only for the DNF-history practice setup) |

### Recommended VM configuration

Practice on a **throwaway VM you can snapshot/revert**, never a machine you care
about — tasks change real system state (users, partitions, services, firewall,
SELinux).

- **vCPUs:** 2
- **RAM:** 2–4 GB
- **Primary disk:** 20 GB (OS)
- **A spare disk for storage practice:** optional. The simulator auto-creates
  500 MB loop devices, so you don't *need* one. If you add a small spare disk
  (e.g. a 1–2 GB `/dev/sda`), it is detected and added to the practice device
  pool automatically — handy for realistic `fdisk`/`parted` partitioning.
- **Install type:** minimal install is fine to launch the simulator, but see
  [Package & service requirements for task scenarios](#package--service-requirements-for-task-scenarios)
  below — several troubleshooting tasks expect packages a minimal install
  doesn't ship with.
- **A second VM (optional):** the real exam runs across two nodes. Link a
  second throwaway VM (**Setup → Link second lab machine**) to unlock the
  [Boot Rescue Lab](#boot-rescue-lab-second-machine) — real root-password
  recovery at that machine's console — and to serve as the NFS server for
  network-storage tasks. Console access to it (virt-manager/VNC) is required.
- **Snapshot first:** take a VM snapshot before a session so you can revert.
- **SELinux:** leave it **Enforcing** for realistic SELinux tasks.
- **Networking:** any NAT/bridged setup; only needed if you want the optional
  DNF transaction-history practice data.

> Cloud VMs (AWS/Azure/GCP) work well — loop devices mean you don't have to
> attach extra block storage to practice LVM/partitioning.

### Package & service requirements for task scenarios

The simulator itself needs nothing beyond the Python standard library. But a
**minimal RHEL/Rocky/Alma install doesn't ship `httpd`, `vsftpd`, or several
other services** that specific tasks (mostly Domain 7 Troubleshooting and
Domain 6 Services) use to build a realistic scenario.

Every launch runs a **read-only preflight check** (`rpm -q`) and warns about
anything missing. When a session's drawn tasks need a missing package, the
simulator **asks (Y/n) whether to install it** at session start — nothing is
ever installed without your consent. If you decline, the affected scenarios
degrade gracefully: SELinux troubleshooting tasks plant the same audit-log
evidence a real denial would have produced (so `ausearch | audit2why` still
leads you to the root cause), and service-based scenarios are skipped.

| Package | Used by |
|---|---|
| `httpd` | Apache SELinux context/boolean, firewall, and service troubleshooting tasks |
| `vsftpd` | FTP service tasks |
| `nfs-utils` | NFS server/client and network storage tasks |
| `samba` | Samba/SMB file sharing tasks |
| `chrony` | time synchronization tasks |
| `firewalld` | firewall management and troubleshooting tasks |
| `bind-utils` | DNS lookup tooling used by networking tasks |
| `tuned` | tuning profile (`tuned-adm`) tasks |

Install everything up front so no task scenario silently fails to set up:

```bash
dnf install -y httpd vsftpd nfs-utils samba chrony firewalld bind-utils tuned
```

**Baseline services** the simulator expects to be able to start/stop/enable —
install the corresponding package above first, then leave the service in
whatever state a fresh install puts it in (tasks manage state themselves):
`httpd`, `vsftpd`, `nfs-server`, `smb`, `chronyd`, `firewalld`, `sshd`,
`crond`, `rsyslog`.

**RHEL 10.x notes:**
- A minimal RHEL 10 install does not include `httpd`, `vsftpd`, `samba`, or
  `tuned` — install them with the command above before an exam/practice
  session that may draw a Domain 6/7 task.
- `firewalld` and `chrony` are installed and enabled by default on RHEL 10, so
  those two are usually already satisfied.
- `nfs-utils` is not installed by default; NFS tasks that provision a
  *remote* server (see the in-app NFS server setup) install it on the
  remote box automatically, but local NFS client tasks still need it here.

---

## Installation

```bash
./install.sh                 # interactive
./install.sh --yes           # unattended (overwrite, no prompts)
./install.sh --no-populate   # skip the optional DNF-history setup
```

The installer checks Python/OS, copies files to `/opt/rhcsa-simulator`, installs
the `rhcsa-simulator` launcher, and optionally builds some DNF transaction
history for the package-history tasks. It auto-detects a non-interactive shell
and runs unattended, so it won't stall in automation.

**Where the launcher goes:** `sudo` ignores your `PATH` and uses `secure_path`
from `/etc/sudoers`, which on RHEL, AlmaLinux and Rocky is:

```
Defaults    secure_path = /sbin:/bin:/usr/sbin:/usr/bin
```

`/usr/local/bin` is not on it, so a launcher installed there works from a root
shell but fails under `sudo` with `sudo: rhcsa-simulator: command not found`.
The installer therefore checks `secure_path` and installs to `/usr/bin` when
`/usr/local/bin` isn't searched, and to `/usr/local/bin` when it is. It prints
the path it chose and verifies the command actually runs before reporting
success.

Run without installing: `sudo python3 rhcsa_simulator.py`.

---

## Usage

### Exam task panel — the closest thing to the real exam

```bash
sudo rhcsa-simulator --exam                              # panel on :8080
sudo rhcsa-simulator --exam --gui 9000                   # move it to another port
sudo rhcsa-simulator --exam --gui-bind 127.0.0.1         # local only
sudo rhcsa-simulator --exam --no-gui                     # terminal only
```

On the day the questions are in a window of their own on the exam desktop —
Red Hat's own application, not a browser and not your terminal. What the
panel reproduces is the *shape* of that: a separate window you keep beside
your shells. You open a task, alt-tab to a shell, work, alt-tab back, lose your
place, scroll, and repeat that twenty-odd times against a clock. Plenty of
people who know the material lose time to exactly that, so it is worth
rehearsing rather than discovering.

The panel is that window:

- **A collapsed list of tasks.** Rows read `Task 07`, nothing more — as on the
  day you cannot triage by skimming, you have to open each one.
- **Click a row and it expands in place** to show the task text, category and
  domain.
- **Revisit and Done on every row.** Independent, so a task can be both, and
  clicking again clears them. The sidebar tallies done / revisit / left.
- **Live countdown**, anchored to uptime so it survives the clock and timezone
  tasks — and a reboot.
- **Light/dark toggle**, remembered per browser.

It prints its URLs at exam start. It binds `0.0.0.0` by default so a headless
exam VM can be read from your laptop's browser; it is unauthenticated and
serves exam questions only — no shell, no control of the box.

If firewalld is blocking the port (the default on a fresh RHEL/Alma install),
the simulator says so at exam start and suggests an SSH forward. It will not
open the port for you: this exam pool contains firewall tasks, and editing
firewalld would corrupt what their validators grade.

```bash
ssh -L 8080:127.0.0.1:8080 root@<exam-vm>   # then browse to 127.0.0.1:8080
```

The ticks are your own bookkeeping — they earn nothing on their own.

**The panel also drives the session:**

- **Submit for grading** — runs the real validators, same as pressing Enter in
  the terminal. Whichever you use, grading happens once, on the exam host.
- **Results** — score, pass/fail, and every check with its message and points,
  per task.
- **Dispute a result** — tick the checks you think are wrong, say why, and
  file it. The report is written to `data/disputes/` **first**, so the evidence
  survives even if submitting fails. If a GitHub issue is opened, the AI
  reviewer posts its verdict as a comment *there* — verdicts do not come back
  into the panel.
- **Reset lab environment** — clears practice mounts, loop devices and
  leftover task artifacts. Refused while an exam is in progress.

**The URL contains a session token** (`?t=…`) and every request must carry it.
That is not decoration: the panel binds `0.0.0.0` so a headless VM can be read
from your laptop, and once it can reset the lab and open GitHub issues,
"whoever can reach the port" stops being an acceptable authorisation rule. A
fresh token is minted per exam. `--gui-bind 127.0.0.1` restricts it further.

### Exam version — v10 (default) or v9

```bash
sudo rhcsa-simulator --exam                    # EX200 v10 (RHEL 10), default
sudo rhcsa-simulator --exam --exam-version 9   # EX200 v9  (RHEL 9)
```

The two exams are not the same syllabus, and the difference is not
symmetric — v9 has an objective section v10 dropped entirely:

| | v9 (RHEL 9) | v10 (RHEL 10) |
|---|---|---|
| **Manage containers** (podman/skopeo, run a service in a container, systemd auto-start, persistent storage) | ✅ own section | ❌ removed |
| **Flatpak** repositories and packages | ❌ | ✅ |
| **systemd timer units** as a scheduling mechanism | ❌ (at/cron only) | ✅ |
| Partition tables | MBR **and** GPT | GPT only |
| set-GID collaboration directories | ✅ | ❌ |
| "Diagnose routine SELinux policy violations" | ✅ explicit | ❌ |

Switching versions changes which tasks can be drawn, the domain weighting,
and what Learn mode shows. Out-of-scope tasks are never generated — being
graded against objectives your exam doesn't contain is worse than a shorter
task pool.

**Container tasks need an image.** Everything else here works offline, but
you can't practise containers without one. Pull one before an exam:

```bash
dnf install -y podman skopeo
podman pull registry.access.redhat.com/ubi9/ubi-minimal
```

If no image is cached, container tasks say so in the task text and the
checks that need a running container are **skipped rather than failed**, so
you're never marked down for a limitation of the lab.

### Terminal menu

Everything works without a browser — pass `--no-gui`:

```bash
sudo rhcsa-simulator    # interactive menu
```

| Key | Mode | What it does |
|---|---|---|
| `Q` | **Quick Practice** | Short session (you pick 4-20 tasks), fast feedback |
| `E` | **Mock Exam** | Full timed exam (20–25 tasks) with setup + reboot-persistence simulation |
| `1` | **Learn Mode** | Study by domain — concepts, commands, tips |
| `2` | **Practice Mode** | One category at a time, with retry & progressive hints |
| `3` | **Adaptive Mode** | SM-2 spaced repetition — focuses weak/overdue areas |
| `4` | **Dashboard** | Stats, history, weak areas |
| `5` | **Export Report** | Write a progress report to `data/` |
| `6` | **Result History** | Drill into past exams (press `d` on a task to dispute a check) |
| `S` | **Setup** | Practice disks, Reset Machine, remote NFS server, DNF-history |
| `0` | Exit | |

### Command-line shortcuts

```bash
rhcsa-simulator --exam               # mock exam + task panel window
rhcsa-simulator --exam --no-gui      # mock exam, terminal only
rhcsa-simulator --exam-version 9     # simulate EX200 v9 (adds containers)
rhcsa-simulator --quick [lvm]        # short practice round (pick 4-20 tasks)
rhcsa-simulator --practice lvm       # practice a specific category
rhcsa-simulator --learn              # study mode
rhcsa-simulator --adaptive           # SM-2 weak-area practice
rhcsa-simulator --list-categories    # categories/domains (no root needed)
rhcsa-simulator --export-code        # print a progress backup code (no root)
rhcsa-simulator --import-code CODE   # restore progress (use - for stdin)
```

---

## Progress snapshots (backup & restore, no login)

Your task history and adaptive (SM-2) state live in a local SQLite DB. Export a
**progress code** — a self-contained, copy-pasteable string — and import it on
any box. No account, no server.

**In the app:** menu → **7. Progress Snapshot** — Export (also saved to
`data/progress_code.txt`), Import (preview, then **Replace** or **Merge**), or
Prune.

**Autosave:** after every recorded result (exam, quick practice, practice,
adaptive) the current progress code is also written to
`/var/lib/rhcsa-progress.code` — outside the install directory, so it survives
a reinstall (`install.sh --yes` wipes `/opt/rhcsa-simulator`, including the
DB). At launch, if that file holds more history than the local DB, the
simulator offers to import (merge) it. Note it lives on the OS drive, so a VM
snapshot revert still rolls it back — export a code manually before reverting.

```bash
rhcsa-simulator --export-code > my-progress.code            # back up
rhcsa-simulator --import-code "$(cat my-progress.code)"     # restore (default: replace)
cat my-progress.code | rhcsa-simulator --import-code - --import-mode merge
```

The code is uppercase-alphanumeric with a checksum, so a mistyped or truncated
code is rejected rather than importing garbage. Its length grows with your
history (a few KB at most).

**Why it matters during active development.** The code is **version-portable** —
it survives *upgrading the simulator itself*, not just OS reinstalls. It encodes
only your history and per-category SM-2 state (never regenerable task text), is
format-versioned (`RH1` / `v:1`) and checksummed, and imports schema-tolerantly,
so a code from an older build loads cleanly into a newer one. The raw SQLite DB
under `data/` is **not** safe to copy across versions (its schema can change) —
the code is the stable interchange format that insulates your progress. So
before anything that wipes or migrates that DB — `git pull` to a new schema,
`./install.sh`, a Reset Machine, a fresh VM, or deleting `data/` — export a
code first, then import it afterward.

> **Caveat:** SM-2 targeting is keyed by **category name**. If a version renames
> or removes a category, that category's history still imports but its
> spaced-repetition schedule won't re-attach. Task-level history is unaffected.

---

## Practice disks & Setup menu

Exams provision disks automatically. To manage them yourself, use **Setup →
Practice Disks**: create loop devices (three 500 MB virtual disks), point at a
real spare disk, or clean up/reset. Every whole-disk task in an exam gets a
**distinct** device from the pool, so an LVM task and a partitioning task never
collide. Loop images live in `/var/lib/rhcsa-simulator/loops/`.

**Setup** also offers:

- **Reset Machine** — *the* single cleanup button. Restores any injected faults
  and task starting-states to their originals, then strips every practice
  artifact: lab files, practice disks & swap, third-party DNF repos, Flatpak
  apps/remotes, scheduled jobs, autofs maps, tuned changes, practice
  users/groups, and remote NFS exports — unmounting every non-system mount
  first. **Preserves** the simulator, your GitHub/SSH connectivity
  (`~/.config/gh`, `~/.ssh`, git config), networking, firewall, SELinux, the
  OS, and all real accounts. Previews everything and requires typing `RESET`.
- **Configure remote NFS server** — SSH into a RHEL box you control and provision
  real, seeded NFS exports for the network-storage tasks (refreshed each exam).
- **Link second lab machine** — register a second box for the Boot Rescue Lab
  and remote scenarios (see below). Can be the same VM as the NFS server.
- **Task Statistics** — per-category counts, plus the list of tasks **flagged
  as bad** ("marked for potential removal"). Hit a task that's just a bad
  question? Type `b` after it in practice, or from its Result History detail —
  it is never offered again in any mode until you unflag it here.
- **Populate Practice Environment** (DNF history).

### When does the machine get cleaned?

- **After a Mock Exam: never automatically.** The environment is deliberately
  left exactly as you finished it, so you can compare your work against the
  scores and file checker disputes with live evidence. Clean up explicitly with
  **Setup → Reset Machine** — or just start the next session, which resets
  everything first.
- **Training sessions** (Quick/Practice/Adaptive) revert all system changes
  **once, at the end of the session** (finish, quit, or Ctrl-C) — not between
  tasks. Practice disks are the one exception: they're wiped between disk tasks
  so the next one gets a clean device.
- **Every session start** restores anything a previous session left behind.

---

## Boot Rescue Lab (second machine)

The real exam expects you to recover a lost root password by interrupting boot
at the console — something a simulator can't fake on its own machine. So the
simulator does it for real, on a **second machine you control**:

1. **Requirements:** a second RHEL/Rocky/Alma VM (or box) on your network that
   you have **console access** to (virt-manager, VNC, or a physical keyboard —
   SSH won't help once the password is gone), plus root SSH once for linking.
2. **Link it** via **Setup → Link second lab machine**. This runs `ssh-copy-id`
   (you type the root password one time) and from then on the simulator uses
   key-based SSH only. The key is its *only* footprint — no agent, nothing
   installed on the lab machine.
3. **Start a scenario** from the main menu (**R — Boot Rescue Lab**): the
   simulator sets a random root password on the lab machine. Go to its console
   and recover it by interrupting boot.
4. **Validate**: over its retained key, the simulator checks that the root hash
   changed, the machine rebooted into a working system, and `/etc/shadow` has
   the correct SELinux label (proof you handled the relabel). Which method you
   used is detected best-effort from the journal and reported as info only.
   Optionally type your new password and it is proven against the live hash.

Both recovery methods are taught and accepted (the walkthrough is built in):

- **`rd.break`** — the classic method: break before `switch_root`, remount
  `/sysroot` rw, `chroot`, `passwd`, `touch /.autorelabel`. **Note:** on some
  builds `rd.break` drops you into a *password-gated* maintenance shell
  ("Give root password for maintenance") instead of a free shell — real exams
  have shipped such machines. When that happens, use:
- **`init=/bin/bash`** — works on every build: bash runs as PID 1, remount `/`
  rw, `passwd`, `restorecon /etc/shadow`. Since systemd isn't running,
  `reboot` fails — reboot with `sync; echo b > /proc/sysrq-trigger` (or
  `/usr/sbin/reboot -f`).

**Safety:** the scenario refuses to start unless key-based SSH works, the
original root hash is kept locally (root-only, 0600), and **Give up** — or
**Reset Machine** — reveals the planted password and restores the original
hash exactly. You cannot be permanently locked out of a bootable machine.

### Remote tasks (two-node exams)

With a lab machine linked, exams and practice sessions also mix in **remote
tasks** — "On the lab machine (…): set the static hostname / create this user /
set the timezone" — just like the real exam's second node. You SSH to the
machine yourself and do the work there; the simulator validates over its own
key and restores the machine's original state at session end (or on Reset
Machine). Without a linked machine these tasks are simply never offered.

---

## Task domains & categories

8 EX200 v10 domains, 25 categories:

1. **Software Management** — packages, repos, flatpak
2. **System Setup & Boot** — boot targets, boot recovery, journald
3. **Users, Groups & Permissions** — users/groups, permissions/ACLs, essential tools
4. **Storage & Filesystems** — partitioning, LVM, filesystems, swap, network storage
5. **Network & DNS** — networking, SSH
6. **Systemd, Services & Processes** — services, timers, processes, time services, troubleshooting
7. **Security** — SELinux, firewall
8. **Automation & Scripting** — scheduling (cron/at/timers), shell scripting

Run `rhcsa-simulator --list-categories` for the live list and per-category counts.

---

## How it works

- **Read-only validation.** Work is graded with whitelisted, timeout-protected,
  read-only commands (`id`, `lsblk`, `systemctl is-active`, `getenforce`, …).
  Only session setup changes state (injecting faults, preparing starting
  states); everything is reversed at training-session end, at next session
  start, or via **Setup → Reset Machine** (see *When does the machine get
  cleaned?* above).
- **Scoring.** Each task has multiple checks with partial credit; default pass
  threshold is 70%. A full exam is 20–25 tasks over a 3-hour timer
  (configurable), followed by a reboot-persistence simulation for tasks that must
  survive a reboot.
- **Progress.** Results and SM-2 state are stored in a local SQLite DB under
  `/opt/rhcsa-simulator/data/` (per-category easiness factor, 1→6→interval×EF).

---

## Disputing a validator result (AI checker disputes)

Think a check graded you wrong? Dispute it and an AI reviewer investigates — and
fixes the checker if you're right.

**File one:** in **Result History** (or after an exam), open a task's detail and
press **`d`**. The simulator captures read-only evidence of the relevant live
system state (category-specific diagnostics like `getfacl` / `lsblk -f`, plus any
command you add) and your written argument, saves a Markdown report under
`data/disputes/`, and opens a labelled GitHub issue (`checker-dispute`) with a
**Checker source** line pointing at the exact task file, class, and `validate()`
line. If the `gh` CLI isn't set up on the box, it prints a pre-filled GitHub "new
issue" URL instead — no token needed locally.

**What happens next:** the `.github/workflows/checker-dispute.yml` Action fires on
the label and runs
[`anthropics/claude-code-action`](https://github.com/anthropics/claude-code-action).
The reviewer opens **only** the named validator, decides strictly from your
evidence whether the checker is genuinely wrong (bad path/grep, inverted
condition, off-by-one, a bad RHEL 10 assumption) or the task simply wasn't done,
posts a **verdict comment**, and — **only if the checker is wrong** — makes the
minimal fix, runs `pytest`, and opens a **fix PR** that closes the issue.

**Enable it on your fork:** under Settings → Secrets and variables → Actions, add
**`CLAUDE_CODE_OAUTH_TOKEN`** (from `claude setup-token`, uses your Claude
subscription) or **`ANTHROPIC_API_KEY`**. The workflow is already scoped
(`id-token: write`) and reads either. Re-run a dispute by removing and re-adding
the `checker-dispute` label (issue-triggered workflows run from the default
branch).

---

## Architecture

```
rhcsa-simulator/
├── rhcsa_simulator.py   # entry point / CLI
├── config/              # settings, exam objectives
├── core/                # exam, practice, learn, adaptive, menu, results_db, reboot
│                        #   dispute, full_reset, nfs_server, lab_cleanup, task_env
├── tasks/               # task definitions by category (+ fault injection/teardown)
├── validators/          # safe read-only validation framework
├── device/              # loop-device / practice-disk management
├── utils/               # helpers, formatting, logging, device pool/allocator
├── .github/workflows/   # checker-dispute.yml — AI reviews disputed validators
└── data/                # SQLite progress DB (+ disputes/ reports)
```

## Extending — adding a task

1. Open the category file (e.g. `tasks/users_groups.py`).
2. Subclass `BaseTask`, decorate with `@TaskRegistry.register("category")`.
3. Implement `generate()` (build the prompt) and `validate()` (return a
   `ValidationResult`).
4. If the task needs a whole disk, set `disk_slots = 1`. If it needs a starting
   state (a process to kill, an LV to extend), add `has_fault_injection = True`
   with `inject_fault()` / `restore_fault()`.

## AI-powered feedback (optional)

Set `ANTHROPIC_API_KEY` to enable line-by-line command analysis. See
[AI_SETUP.md](AI_SETUP.md).

## Troubleshooting

- **"must be run as root"** — launch with `sudo`.
- **`sudo: rhcsa-simulator: command not found`** — you have an old install that
  put the launcher in `/usr/local/bin`, which `sudo` does not search on
  RHEL/Alma/Rocky (see [Installation](#installation)). Re-run `./install.sh`,
  which relocates it and removes the stale copy. To confirm afterwards:
  `sudo rhcsa-simulator --list-categories`. Until then, the full path works:
  `sudo /usr/local/bin/rhcsa-simulator`.
- **Storage tasks fail in a container** — loop devices/SELinux/systemd may be
  limited; use a real RHEL/Rocky/Alma VM.
- **Messy state after a crash / want a clean box** — run **Setup → Reset
  Machine**. It restores active faults, unmounts every non-system mount, and
  clears stale mounts/repos/flatpaks/practice users in one pass.
- **Reinstall from scratch** — re-run `./install.sh --yes`.
- **`fdisk` warns that re-reading the partition table failed:**

  ```
  Command (m for help): w
  The partition table has been altered.
  Calling ioctl() to re-read partition table.
  Re-reading the partition table failed.: Invalid argument

  The kernel still uses the old table. The new table will be used at the next reboot or after you run partprobe(8) or partx(8).
  ```

  Run `partprobe /dev/diskthatchanged` (e.g. `partprobe /dev/sdb`) to make the
  kernel re-read the partition table and clear the error.

## License

See [LICENSE](LICENSE).
