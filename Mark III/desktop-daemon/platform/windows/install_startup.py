"""
MARK III — Windows Startup Registration Utility

Writes / removes the HKCU Run key so the daemon auto-launches silently
at user login via pythonw.exe (no console window).

Run as the target user — does NOT require administrator elevation because
HKCU is always writable by the current user.

Usage:
    python install_startup.py install    # register
    python install_startup.py remove     # deregister
    python install_startup.py status     # print current value
"""

import sys
import winreg
from pathlib import Path

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_APP_NAME    = "MarkIII"
_RUN_KEY     = r"Software\Microsoft\Windows\CurrentVersion\Run"

# Resolve absolute path to the daemon entry point at install time so the key
# stays valid even if the working directory changes later.
_DAEMON_ENTRY = Path(__file__).resolve().parent.parent.parent / "daemon" / "main.py"


def _pythonw() -> Path:
    """Return the path to pythonw.exe in the current interpreter's prefix."""
    pythonw = Path(sys.executable).parent / "pythonw.exe"
    if not pythonw.exists():
        # Fallback: some venvs nest the exe one level deeper
        pythonw = Path(sys.executable).parent.parent / "pythonw.exe"
    if not pythonw.exists():
        raise FileNotFoundError(
            "pythonw.exe not found alongside the current interpreter. "
            "Are you running inside a venv? Activate it first."
        )
    return pythonw


def _build_command() -> str:
    """
    Build the launch command written into the registry value.
    Uses pythonw.exe so no console window appears at login.
    Wraps both paths in quotes to handle spaces (e.g. 'Program Files').
    """
    return f'"{_pythonw()}" "{_DAEMON_ENTRY}"'


# ---------------------------------------------------------------------------
# Registry helpers
# ---------------------------------------------------------------------------

def _open_run_key(access: int) -> winreg.HKEYType:
    return winreg.OpenKey(winreg.HKEY_CURRENT_USER, _RUN_KEY, 0, access)


def install() -> None:
    """Register the daemon to start on user login."""
    if not _DAEMON_ENTRY.exists():
        raise FileNotFoundError(
            f"Daemon entry point not found: {_DAEMON_ENTRY}\n"
            "Run install_startup.py from inside the desktop-daemon directory."
        )

    command = _build_command()

    with _open_run_key(winreg.KEY_SET_VALUE) as key:
        winreg.SetValueEx(key, _APP_NAME, 0, winreg.REG_SZ, command)

    print(f"[MARK III] Startup entry installed.")
    print(f"  Key   : HKCU\\{_RUN_KEY}")
    print(f"  Name  : {_APP_NAME}")
    print(f"  Value : {command}")
    print()
    print("MARK III will launch silently the next time you log in.")


def remove() -> None:
    """Deregister the daemon from startup."""
    try:
        with _open_run_key(winreg.KEY_SET_VALUE) as key:
            winreg.DeleteValue(key, _APP_NAME)
        print(f"[MARK III] Startup entry removed.")
    except FileNotFoundError:
        print(f"[MARK III] No startup entry found — nothing to remove.")


def status() -> None:
    """Print the current registry value, if any."""
    try:
        with _open_run_key(winreg.KEY_READ) as key:
            value, _ = winreg.QueryValueEx(key, _APP_NAME)
        print(f"[MARK III] Startup entry is ACTIVE.")
        print(f"  Value : {value}")
    except FileNotFoundError:
        print("[MARK III] No startup entry found (daemon is NOT set to auto-start).")


# ---------------------------------------------------------------------------
# CLI dispatcher
# ---------------------------------------------------------------------------

_COMMANDS = {
    "install": install,
    "remove":  remove,
    "status":  status,
}

if __name__ == "__main__":
    if len(sys.argv) != 2 or sys.argv[1] not in _COMMANDS:
        print(__doc__)
        sys.exit(1)

    try:
        _COMMANDS[sys.argv[1]]()
    except Exception as exc:
        print(f"[ERROR] {exc}", file=sys.stderr)
        sys.exit(1)
