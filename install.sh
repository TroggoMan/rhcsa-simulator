#!/bin/bash
#
# RHCSA Mock Exam Simulator - Installation Script
#
# This script installs the RHCSA simulator to /opt/rhcsa-simulator
# and creates a symlink for easy access.
#

set -e

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Configuration
INSTALL_DIR="/opt/rhcsa-simulator"
CMD_NAME="rhcsa-simulator"
REQUIRED_PYTHON_VERSION="3.6"

# Where the launcher goes is decided below by pick_bin_dir(), because the
# conventional choice (/usr/local/bin) is NOT on sudo's secure_path on
# RHEL-family systems — see the comment there.
BIN_DIR=""
BIN_LINK=""

# Candidate launcher locations, cleaned up on reinstall so an old copy in the
# location we're no longer using can't shadow the new one.
ALL_BIN_DIRS="/usr/local/bin /usr/bin"

echo "========================================="
echo "RHCSA Mock Exam Simulator - Installation"
echo "========================================="
echo

# Check if running as root
if [ "$EUID" -ne 0 ]; then
    echo -e "${RED}Error: This script must be run as root${NC}"
    echo "Please run: sudo ./install.sh"
    exit 1
fi

# Check Python version
echo "Checking Python version..."
if ! command -v python3 &> /dev/null; then
    echo -e "${RED}Error: Python 3 is not installed${NC}"
    echo "Please install Python 3.6 or later"
    exit 1
fi

# Resolve the interpreter to an absolute path — the launcher runs under sudo's
# secure_path, which may not be the PATH that found python3 here.
PYTHON_BIN=$(command -v python3)
PYTHON_VERSION=$(python3 -c 'import sys; print(".".join(map(str, sys.version_info[:2])))')
echo "Found Python ${PYTHON_VERSION} at ${PYTHON_BIN}"

if [ "$(printf '%s\n' "$REQUIRED_PYTHON_VERSION" "$PYTHON_VERSION" | sort -V | head -n1)" != "$REQUIRED_PYTHON_VERSION" ]; then
    echo -e "${RED}Error: Python ${REQUIRED_PYTHON_VERSION} or later is required${NC}"
    exit 1
fi

# Check OS.
#
# /etc/redhat-release alone only tells us "some Red Hat derivative". Read
# os-release too so the install names the distro and version it actually
# found — a mis-identified box is the root of every "it didn't work on
# <distro>" report, and it should be visible here rather than three tasks in.
echo "Checking operating system..."
OS_ID=""
OS_MAJOR=""
OS_PRETTY=""
if [ -r /etc/os-release ]; then
    # shellcheck disable=SC1091
    . /etc/os-release
    OS_ID="${ID:-}"
    OS_MAJOR="${VERSION_ID%%.*}"
    OS_PRETTY="${PRETTY_NAME:-${NAME:-}}"
fi

if [ -z "$OS_PRETTY" ] && [ -f /etc/redhat-release ]; then
    OS_PRETTY=$(cat /etc/redhat-release)
fi

case "$OS_ID" in
    rhel|almalinux|rocky|centos|ol|fedora)
        echo "Detected: ${OS_PRETTY}"
        case "$OS_MAJOR" in
            9|10) ;;
            *)
                echo -e "${YELLOW}Warning: EX200 v10 targets major version 10 (9 is usable).${NC}"
                echo -e "${YELLOW}Version ${OS_MAJOR} may not match what the tasks expect.${NC}"
                read -p "Continue anyway? [y/N]: " -n 1 -r
                echo
                if [[ ! $REPLY =~ ^[Yy]$ ]]; then
                    exit 1
                fi
                ;;
        esac
        ;;
    *)
        if [ -n "$OS_PRETTY" ]; then
            echo -e "${YELLOW}Detected: ${OS_PRETTY}${NC}"
        fi
        echo -e "${YELLOW}Warning: This tool is designed for RHEL / AlmaLinux / Rocky Linux 9-10.${NC}"
        echo -e "${YELLOW}Package names, SELinux, firewalld and boot layout differ elsewhere,${NC}"
        echo -e "${YELLOW}so most tasks will not grade correctly.${NC}"
        read -p "Continue anyway? [y/N]: " -n 1 -r
        echo
        if [[ ! $REPLY =~ ^[Yy]$ ]]; then
            exit 1
        fi
        ;;
esac

# Create installation directory
echo "Creating installation directory..."
if [ -d "$INSTALL_DIR" ]; then
    echo -e "${YELLOW}Warning: Installation directory already exists${NC}"
    read -p "Remove existing installation? [y/N]: " -n 1 -r
    echo
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        rm -rf "$INSTALL_DIR"
    else
        echo "Installation cancelled"
        exit 1
    fi
fi

mkdir -p "$INSTALL_DIR"

# Copy files
echo "Copying files..."
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"

cp -r "$SCRIPT_DIR"/* "$INSTALL_DIR/"

# Set permissions
echo "Setting permissions..."
chmod -R 644 "$INSTALL_DIR"/*.py
chmod -R 755 "$INSTALL_DIR"/{config,core,tasks,validators,utils}
chmod -R 755 "$INSTALL_DIR"/data
chmod 755 "$INSTALL_DIR/rhcsa_simulator.py"

# Install the launcher
#
# This used to be a bare symlink into /usr/local/bin. `sudo rhcsa-simulator`
# then failed with "command not found", because sudo does not use your PATH —
# it uses secure_path from /etc/sudoers, and on RHEL/AlmaLinux/Rocky that is:
#
#     Defaults    secure_path = /sbin:/bin:/usr/sbin:/usr/bin
#
# No /usr/local/bin. So the one command the README told people to run was the
# one that could not resolve. (It works from a root login shell, which is why
# it went unnoticed.) Pick a directory sudo will actually search.
# Overridable so this can be exercised against fixture files in a test.
SUDOERS_PATHS="${SUDOERS_PATHS:-/etc/sudoers /etc/sudoers.d/}"

pick_bin_dir() {
    local secure_path
    # Later entries win, so take the last secure_path we can find.
    # shellcheck disable=SC2086
    secure_path=$(grep -rhs '^[[:space:]]*Defaults.*secure_path' \
                    $SUDOERS_PATHS 2>/dev/null \
                  | tail -n1)

    if [ -z "$secure_path" ]; then
        # No secure_path directive: sudo passes PATH through, so the
        # conventional location is correct.
        echo "/usr/local/bin"
        return
    fi

    case "$secure_path" in
        *=*/usr/local/bin*|*:/usr/local/bin*|*/usr/local/bin:*)
            echo "/usr/local/bin" ;;
        *)
            # /usr/local/bin is not searched by sudo on this box. Use /usr/bin
            # so the documented `sudo rhcsa-simulator` resolves. Editing
            # secure_path in sudoers would also work but risks breaking sudo
            # entirely on a box someone is mid-exam on — not worth it.
            echo "/usr/bin" ;;
    esac
}

BIN_DIR="$(pick_bin_dir)"
BIN_LINK="${BIN_DIR}/${CMD_NAME}"

echo "Installing launcher..."
echo "  sudo searches ${BIN_DIR} — installing there"

# Drop any launcher from a previous install in either candidate directory, so
# a stale copy can't win the PATH lookup ahead of this one.
for dir in $ALL_BIN_DIRS; do
    old="${dir}/${CMD_NAME}"
    if [ "$old" != "$BIN_LINK" ] && { [ -L "$old" ] || [ -f "$old" ]; }; then
        echo "  removing previous launcher at ${old}"
        rm -f "$old"
    fi
done
rm -f "$BIN_LINK"

# A wrapper rather than a symlink: it names the interpreter and the script
# explicitly, so it does not depend on the .py file's executable bit, on the
# shebang resolving, or on how Python treats a symlinked entry point.
cat > "$BIN_LINK" <<EOF
#!/bin/bash
# RHCSA Mock Exam Simulator launcher. Generated by install.sh — edits here are
# overwritten on reinstall.
exec ${PYTHON_BIN} ${INSTALL_DIR}/rhcsa_simulator.py "\$@"
EOF
chmod 755 "$BIN_LINK"

# Create requirements.txt (empty - stdlib only)
echo "# No external dependencies required - Python stdlib only" > "$INSTALL_DIR/requirements.txt"

# Verify installation
#
# Actually launch the command instead of just checking that a file exists —
# the previous check confirmed a symlink was present, which it always was,
# while the command it pointed at could not be run.
echo "Verifying installation..."
INSTALL_OK=1

if [ ! -f "$INSTALL_DIR/rhcsa_simulator.py" ]; then
    echo -e "${RED}✗ ${INSTALL_DIR}/rhcsa_simulator.py is missing${NC}"
    INSTALL_OK=0
fi

if [ ! -x "$BIN_LINK" ]; then
    echo -e "${RED}✗ launcher ${BIN_LINK} is missing or not executable${NC}"
    INSTALL_OK=0
elif ! "$BIN_LINK" --list-categories >/dev/null 2>&1; then
    echo -e "${RED}✗ ${BIN_LINK} exists but failed to run${NC}"
    echo "  Try it directly to see the error:"
    echo "    ${PYTHON_BIN} ${INSTALL_DIR}/rhcsa_simulator.py --list-categories"
    INSTALL_OK=0
fi

# Confirm the bare command resolves under sudo's own PATH, which is the way
# the README tells people to start it.
RESOLVED=$(env -i PATH="$(getconf PATH 2>/dev/null || echo /usr/bin:/bin)" \
           command -v "$CMD_NAME" 2>/dev/null)
if [ "$INSTALL_OK" -eq 1 ] && [ -z "$RESOLVED" ]; then
    echo -e "${YELLOW}Warning: '${CMD_NAME}' did not resolve on a minimal PATH.${NC}"
    echo -e "${YELLOW}If 'sudo ${CMD_NAME}' says command not found, use:${NC}"
    echo "    sudo ${BIN_LINK}"
fi

if [ "$INSTALL_OK" -eq 1 ]; then
    echo -e "${GREEN}✓ Installation successful!${NC}"
    echo
    echo "Installation Details:"
    echo "  Location:   $INSTALL_DIR"
    echo "  Launcher:   $BIN_LINK"
    echo
    echo "Usage:"
    echo "  sudo ${CMD_NAME}              # or: sudo ${BIN_LINK}"
    echo
    echo -e "${YELLOW}Note: You must run as root (sudo) to validate system state${NC}"
else
    echo -e "${RED}✗ Installation failed${NC}"
    exit 1
fi

echo
echo "========================================="
echo "Installing fstab safety guard"
echo "========================================="
echo
# The simulator and candidate add /etc/fstab entries (swap, mounts, fault
# injection). If a session is interrupted those can be left behind and break the
# next boot. This guard restores a known-good baseline at shutdown and early
# boot so the system always comes up clean.
GUARD_SRC="$SCRIPT_DIR/tools/rhcsa-fstab-guard.sh"
GUARD_UNIT_SRC="$SCRIPT_DIR/tools/rhcsa-fstab-guard.service"
GUARD_DST="/usr/local/sbin/rhcsa-fstab-guard.sh"
GUARD_UNIT_DST="/etc/systemd/system/rhcsa-fstab-guard.service"

if [ -f "$GUARD_SRC" ] && [ -f "$GUARD_UNIT_SRC" ]; then
    install -m 755 "$GUARD_SRC" "$GUARD_DST"
    install -m 644 "$GUARD_UNIT_SRC" "$GUARD_UNIT_DST"

    # Capture the current (clean) fstab as the baseline.
    "$GUARD_DST" init || echo -e "${YELLOW}Warning: could not capture fstab baseline (fstab not currently valid?)${NC}"

    if command -v systemctl >/dev/null 2>&1; then
        systemctl daemon-reload
        if systemctl enable rhcsa-fstab-guard.service >/dev/null 2>&1; then
            # Activate now so the shutdown hook is armed this boot too.
            systemctl start rhcsa-fstab-guard.service >/dev/null 2>&1 || true
            echo -e "${GREEN}✓ fstab guard installed and enabled${NC}"
        else
            echo -e "${YELLOW}Warning: could not enable rhcsa-fstab-guard.service${NC}"
        fi
    else
        echo -e "${YELLOW}systemctl not available — guard installed but not enabled${NC}"
    fi
else
    echo -e "${YELLOW}Guard files not found in tools/ — skipping${NC}"
fi

echo
echo "========================================="
echo "Optional: Populate Practice Environment"
echo "========================================="
echo
echo "Some practice tasks (e.g. DNF history) work best with a populated"
echo "transaction history. This installs and removes small packages to"
echo "build up ~12 DNF transactions. Nothing is permanently changed."
echo
read -p "Populate DNF transaction history now? [Y/n]: " -r
echo
if [[ ! $REPLY =~ ^[Nn]$ ]]; then
    echo "Building DNF transaction history..."
    PRACTICE_PKGS=(tree dos2unix bc mtr strace lsof pv screen nmap zip ltrace telnet whois jq)
    CYCLES=0
    TARGET=12
    for pkg in "${PRACTICE_PKGS[@]}"; do
        if [ "$CYCLES" -ge "$TARGET" ]; then
            break
        fi
        if rpm -q "$pkg" &>/dev/null; then
            continue  # already installed — skip
        fi
        echo "  Installing $pkg..."
        if dnf install -y --quiet "$pkg" &>/dev/null 2>&1; then
            echo "  Removing $pkg..."
            dnf remove -y --quiet "$pkg" &>/dev/null 2>&1
            CYCLES=$((CYCLES + 1))
        fi
    done
    if [ "$CYCLES" -gt 0 ]; then
        echo -e "${GREEN}✓ Completed $CYCLES install/remove cycles ($((CYCLES * 2)) new DNF transactions)${NC}"
    else
        echo -e "${YELLOW}No cycles completed — check DNF repo access with: dnf repolist${NC}"
    fi
else
    echo "Skipped. Run 'Setup → Populate Practice Environment' in the simulator later."
fi

echo
echo "========================================="
echo "Installation Complete!"
echo "========================================="
