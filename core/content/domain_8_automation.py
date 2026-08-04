"""
Domain 8: Automation & Scripting
Categories: scheduling, scripting
"""

CONTENT = {
    "scheduling": {
        "name": "Task Scheduling (cron & at)",
        "explanation": """
Task scheduling uses cron for recurring jobs and at for one-time jobs.
You must know crontab syntax (minute hour day month weekday).

CRONTAB SYNTAX:
  MIN  HOUR  DAY  MONTH  WEEKDAY  COMMAND
  0-59 0-23  1-31 1-12   0-7      /path/to/command

  *     = every value
  */N   = every N units
  1,3,5 = specific values
  1-5   = range of values

SPECIAL STRINGS:
  @reboot   = Run once at startup
  @daily    = Run once a day (0 0 * * *)
  @weekly   = Run once a week (0 0 * * 0)
  @monthly  = Run once a month (0 0 1 * *)
  @hourly   = Run once an hour (0 * * * *)

CRONTAB FILES:
  /etc/crontab           - System crontab
  /var/spool/cron/<user> - Per-user crontabs
  /etc/cron.d/           - Drop-in cron files
  /etc/cron.daily/       - Scripts run daily
  /etc/cron.hourly/      - Scripts run hourly

ACCESS CONTROL:
  /etc/cron.allow  - Users allowed to use cron (if exists, only these users)
  /etc/cron.deny   - Users denied cron access
  /etc/at.allow    - Users allowed to use at
  /etc/at.deny     - Users denied at access
        """,
        "commands": [
            {
                "name": "Edit Crontab",
                "syntax": "crontab -e [-u <user>]",
                "example": "crontab -e -u alice",
                "flags": {
                    "-e": "Edit crontab",
                    "-l": "List crontab entries",
                    "-r": "Remove all crontab entries",
                    "-u user": "Operate on another user's crontab (root only)",
                },
            },
            {
                "name": "Crontab Syntax",
                "syntax": "MIN HOUR DAY MONTH WEEKDAY COMMAND",
                "example": "30 2 * * * /usr/local/bin/backup.sh",
                "flags": {
                    "*": "Every value in field",
                    "*/N": "Every N units (e.g., */15 = every 15 min)",
                    "1,3,5": "Specific values",
                    "1-5": "Range (e.g., Mon-Fri for weekday)",
                    "0 2 * * *": "Daily at 2:00 AM",
                    "*/10 * * * *": "Every 10 minutes",
                    "0 9 * * 1-5": "Weekdays at 9:00 AM",
                },
            },
            {
                "name": "One-Time Task (at)",
                "syntax": "at <time>",
                "example": "echo '/usr/bin/report.sh' | at 22:00\nat 2:00 AM tomorrow",
                "flags": {
                    "at <time>": "Schedule one-time task",
                    "atq": "List pending at jobs",
                    "atrm <job>": "Remove pending at job",
                    "at now + 5 minutes": "Relative time",
                    "at 10:00 AM Dec 25": "Specific date/time",
                },
            },
            {
                "name": "Restrict Cron Access",
                "syntax": "echo '<username>' >> /etc/cron.allow",
                "example": "echo 'alice' >> /etc/cron.allow\necho 'bob' >> /etc/cron.deny",
                "flags": {
                    "/etc/cron.allow": "If exists, ONLY listed users can use cron",
                    "/etc/cron.deny": "Listed users are denied (if no .allow file)",
                    "Priority": "allow file checked first; if exists, deny is ignored",
                    "Neither exists": "Only root can use cron (RHEL default: deny exists empty)",
                },
            },
        ],
        "common_mistakes": [
            "Wrong field order (MIN HOUR DAY MONTH WEEKDAY, not HOUR MIN...)",
            "Forgetting absolute paths in cron commands",
            "Not redirecting output (cron sends email on output)",
            "Confusing day-of-week values (0=Sun, 7=Sun, 1=Mon)",
            "Editing /etc/crontab instead of using 'crontab -e'",
            "Forgetting to install at package (dnf install at)",
        ],
        "exam_tricks": [
            "Crontab: MIN HOUR DAY MONTH WEEKDAY (memorize this order)",
            "0 2 * * * = 2:00 AM daily",
            "*/5 * * * * = every 5 minutes",
            "Always use absolute paths in cron entries",
            "Redirect output: >> /var/log/backup.log 2>&1",
            "'crontab -l -u root' to check existing cron entries",
        ],
    },
    "scripting": {
        "name": "Shell Scripting (Bash)",
        "explanation": """
Shell scripting is essential for automating tasks in Linux. The RHCSA exam
tests your ability to write basic bash scripts with conditionals, loops,
command-line arguments, and proper exit codes.

SCRIPT STRUCTURE:
  #!/bin/bash          - Shebang (interpreter directive)
  # Comments           - Explain your code
  commands             - Script body
  exit 0               - Exit with success status

VARIABLES:
  name="value"         - Assignment (NO spaces around =)
  $name or ${name}     - Variable expansion
  "$name"              - Quoted expansion (preserves spaces)
  $1, $2, ...          - Positional parameters (arguments)
  $#                   - Number of arguments
  $@                   - All arguments as separate words
  $*                   - All arguments as single word
  $?                   - Exit status of last command
  $$                   - Current script's PID

EXIT CODES:
  0                    - Success
  1-255                - Various error conditions
  exit N               - Exit with specific code
        """,
        "commands": [
            {
                "name": "Basic Script Structure",
                "syntax": "#!/bin/bash\\n# Description\\ncommands\\nexit 0",
                "example": "#!/bin/bash\\necho 'Hello World'\\nexit 0",
                "flags": {
                    "#!/bin/bash": "Shebang - specifies interpreter",
                    "chmod +x": "Make script executable",
                    "./script.sh": "Execute script",
                    "bash script.sh": "Run with bash explicitly",
                },
            },
            {
                "name": "Conditionals (if/else)",
                "syntax": "if [ condition ]; then\\n  commands\\nfi",
                "example": "if [ -f /etc/passwd ]; then\\n  echo 'File exists'\\nfi",
                "flags": {
                    "[ ]": "Test command (spaces required!)",
                    "[[ ]]": "Extended test (bash-specific)",
                    "-f file": "File exists and is regular file",
                    "-d dir": "Directory exists",
                    "-e path": "Path exists (file or dir)",
                    "-r/-w/-x": "Readable/writable/executable",
                    "-z string": "String is empty",
                    "-n string": "String is not empty",
                    "str1 = str2": "Strings are equal",
                    "-eq/-ne/-lt/-gt/-le/-ge": "Numeric comparisons",
                },
            },
            {
                "name": "Loops (for)",
                "syntax": "for var in list; do\\n  commands\\ndone",
                "example": "for file in /etc/*.conf; do\\n  echo $file\\ndone",
                "flags": {
                    "for i in 1 2 3": "Iterate over list",
                    "for i in {1..10}": "Brace expansion range",
                    "for i in $(seq 1 10)": "Command substitution",
                    "for file in *.txt": "Glob patterns",
                    'for arg in "$@"': "Iterate over arguments",
                },
            },
            {
                "name": "Loops (while)",
                "syntax": "while [ condition ]; do\\n  commands\\ndone",
                "example": "count=1\\nwhile [ $count -le 5 ]; do\\n  echo $count\\n  ((count++))\\ndone",
                "flags": {
                    "while true": "Infinite loop",
                    "while read line": "Read file line by line",
                    "break": "Exit loop immediately",
                    "continue": "Skip to next iteration",
                },
            },
            {
                "name": "Command-Line Arguments",
                "syntax": "$1, $2, $#, $@",
                "example": '#!/bin/bash\\necho "Script: $0"\\necho "First arg: $1"\\necho "All args: $@"\\necho "Count: $#"',
                "flags": {
                    "$0": "Script name",
                    "$1, $2, ...": "Positional arguments",
                    "$#": "Number of arguments",
                    "$@": "All arguments (preserves quoting)",
                    "$*": "All arguments (single string)",
                    "shift": "Shift arguments left",
                },
            },
            {
                "name": "Exit Codes",
                "syntax": "exit N",
                "example": "if [ ! -f \"$1\" ]; then\\n  echo 'File not found'\\n  exit 1\\nfi\\nexit 0",
                "flags": {
                    "exit 0": "Success",
                    "exit 1": "General error",
                    "$?": "Check last exit code",
                    "command && echo 'ok'": "Run if success",
                    "command || echo 'failed'": "Run if failure",
                },
            },
            {
                "name": "Command Substitution",
                "syntax": "$(command) or `command`",
                "example": "today=$(date +%Y-%m-%d)\\nfiles=$(ls -1 | wc -l)",
                "flags": {
                    "$(command)": "Preferred syntax",
                    "`command`": "Legacy syntax (avoid)",
                    "Nesting": "$(cmd1 $(cmd2)) works with $()",
                },
            },
        ],
        "common_mistakes": [
            "Missing spaces in [ ] test: [ $a -eq 1 ] not [$a -eq 1]",
            "Using = for numeric comparison (use -eq instead)",
            "Forgetting quotes around variables with spaces",
            "Missing shebang line (#!/bin/bash)",
            "Script not executable (chmod +x needed)",
            "Spaces around = in assignment: var=value not var = value",
            "Using single [ ] with && or || (use [[ ]] instead)",
            "Forgetting 'then' after if condition",
        ],
        "exam_tricks": [
            "Always start with #!/bin/bash shebang",
            "Always chmod +x your script",
            "Test conditions: -f for files, -d for directories",
            'Use "$@" (quoted) to preserve argument spacing',
            "Exit 0 for success, non-zero for errors",
            "Use $? to check if previous command succeeded",
            "bash -n script.sh to check syntax without running",
            "A directory the task tells you to read from may legitimately be "
            "EMPTY. That is not a hint that you set something up wrong — you "
            "are graded on the script, not on it having produced output. Write "
            "it, make it executable, run it, confirm it exits 0, move on.",
            "Don't hardcode around the data you happen to see. 'Copy the "
            "contents of /foo to /bar' means cp -a /foo/. /bar/ (or rsync), "
            "which is correct whether /foo holds 0 files or 500.",
        ],
    },
}
