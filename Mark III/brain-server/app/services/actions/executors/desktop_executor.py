"""
MARK III — Desktop Executor (Phase 12B)

Handles:
  launch_app, focus_app, close_app    — application lifecycle
  run_command                         — shell commands (DANGEROUS)
  install_software                    — package managers (DANGEROUS)
  write_clipboard                     — clipboard write
  kill_process                        — process termination (DANGEROUS)
  system_shutdown, system_restart     — CRITICAL power actions

Platform-aware:
  Windows  → os.startfile / subprocess / winreg / pygetwindow
  macOS    → subprocess open / osascript
  Linux    → xdg-open / subprocess

Optional packages: pygetwindow (window focus), pyperclip (clipboard)
All degrade gracefully if unavailable.
"""

from __future__ import annotations

import asyncio
import logging
import os
import platform
import shutil
import subprocess
import sys
import time
from typing import Optional

from app.services.actions.base_action import Action, ActionResult, ActionType
from app.services.actions.app_aliases import resolve_app_name

logger = logging.getLogger(__name__)

_PLATFORM = platform.system()   # "Windows" | "Darwin" | "Linux"

# Optional: pygetwindow for window focus
try:
    import pygetwindow as gw
    _GW_AVAILABLE = True
except ImportError:
    _GW_AVAILABLE = False

# Optional: pyperclip for clipboard
try:
    import pyperclip
    _CLIP_AVAILABLE = True
except ImportError:
    _CLIP_AVAILABLE = False


# ---------------------------------------------------------------------------
# Base executor interface
# ---------------------------------------------------------------------------

class BaseExecutor:
    async def run(self, action: Action) -> ActionResult:
        raise NotImplementedError


# ---------------------------------------------------------------------------
# Desktop Executor
# ---------------------------------------------------------------------------

class DesktopExecutor(BaseExecutor):

    async def run(self, action: Action) -> ActionResult:
        t0 = time.monotonic()
        try:
            result = await self._dispatch(action)
        except Exception as exc:
            result = ActionResult(
                success=False, error=str(exc),
                latency_ms=(time.monotonic() - t0) * 1000,
            )
        result.latency_ms = (time.monotonic() - t0) * 1000
        return result

    async def _dispatch(self, action: Action) -> ActionResult:
        t = action.action_type
        p = action.parameters

        if t == ActionType.LAUNCH_APP:
            return await asyncio.to_thread(self._launch_app, p["app_name"], p.get("path"))
        if t == ActionType.FOCUS_APP:
            return await asyncio.to_thread(self._focus_app, p["app_name"])
        if t == ActionType.CLOSE_APP:
            return await asyncio.to_thread(self._close_app, p["app_name"])
        if t == ActionType.RUN_COMMAND:
            return await self._run_command(
                p["command"], p.get("cwd"), float(p.get("timeout", 30))
            )
        if t == ActionType.INSTALL_SOFTWARE:
            return await self._install_software(p["package"], p.get("manager"))
        if t == ActionType.WRITE_CLIPBOARD:
            return await asyncio.to_thread(self._write_clipboard, p["text"])
        if t == ActionType.KILL_PROCESS:
            return await asyncio.to_thread(self._kill_process, p["target"], bool(p.get("force")))
        if t == ActionType.SYSTEM_SHUTDOWN:
            return await asyncio.to_thread(self._system_shutdown, int(p.get("delay_seconds", 0)))
        if t == ActionType.SYSTEM_RESTART:
            return await asyncio.to_thread(self._system_restart, int(p.get("delay_seconds", 0)))
        if t == ActionType.MODIFY_REGISTRY:
            return await asyncio.to_thread(
                self._modify_registry, p["key"], p["value_name"], p["value_data"], p.get("value_type", "REG_SZ")
            )
        return ActionResult(success=False, error=f"Unknown desktop action: {t}")

    # ------------------------------------------------------------------
    # App lifecycle
    # ------------------------------------------------------------------

    def _launch_app(self, app_name: str, path: Optional[str] = None) -> ActionResult:
        # Fuzzy-correct mis-transcribed app names ("node pad" -> "notepad")
        # before attempting resolution. Falls through unchanged if no
        # confident match — never blocks launching an unrecognized app.
        resolved_name = resolve_app_name(app_name) if not path else app_name
        target = path or resolved_name
        try:
            if _PLATFORM == "Windows":
                if path and os.path.exists(path):
                    os.startfile(path)
                else:
                    # Try to resolve via where/which first
                    resolved = (
                        shutil.which(resolved_name)
                        or shutil.which(resolved_name.replace(" ", ""))
                        or shutil.which(app_name)
                        or shutil.which(app_name.replace(" ", ""))
                    )
                    if resolved:
                        subprocess.Popen([resolved], shell=False)
                    else:
                        os.startfile(resolved_name)   # fallback — may work for registered apps
            elif _PLATFORM == "Darwin":
                subprocess.Popen(["open", "-a", resolved_name])
            else:
                resolved = (
                    shutil.which(resolved_name.lower().replace(" ", "-"))
                    or shutil.which(resolved_name.lower())
                )
                if resolved:
                    subprocess.Popen([resolved])
                else:
                    subprocess.Popen(["xdg-open", target])
            launched_as = f" (as '{resolved_name}')" if resolved_name != app_name else ""
            return ActionResult(success=True, output=f"Launched '{app_name}'{launched_as}")
        except Exception as exc:
            return ActionResult(success=False, error=f"Could not launch '{app_name}': {exc}")

    def _focus_app(self, app_name: str) -> ActionResult:
        if _GW_AVAILABLE:
            wins = gw.getWindowsWithTitle(app_name)
            if wins:
                try:
                    wins[0].activate()
                    return ActionResult(success=True, output=f"Focused '{app_name}'")
                except Exception as exc:
                    return ActionResult(success=False, error=str(exc))
        # Fallback: launch it (often brings it to front if already open)
        return self._launch_app(app_name)

    def _close_app(self, app_name: str) -> ActionResult:
        if _GW_AVAILABLE:
            wins = gw.getWindowsWithTitle(app_name)
            if wins:
                try:
                    wins[0].close()
                    return ActionResult(success=True, output=f"Closed '{app_name}'")
                except Exception as exc:
                    return ActionResult(success=False, error=str(exc))

        resolved_name = resolve_app_name(app_name)
        if _PLATFORM == "Windows":
            result = subprocess.run(["taskkill", "/F", "/IM", f"{resolved_name}.exe"], capture_output=True)
            if result.returncode == 0:
                return ActionResult(success=True, output=f"Killed '{app_name}'")
        elif _PLATFORM == "Darwin":
            result = subprocess.run(["osascript", "-e", f'quit app "{resolved_name}"'], capture_output=True)
            if result.returncode == 0:
                return ActionResult(success=True, output=f"Quit '{app_name}'")
        else:
            result = subprocess.run(["pkill", "-f", app_name], capture_output=True)
            if result.returncode == 0:
                return ActionResult(success=True, output=f"Killed '{app_name}'")

        return ActionResult(success=False, error=f"Could not close '{app_name}' — window not found")

    # ------------------------------------------------------------------
    # Shell command
    # ------------------------------------------------------------------

    async def _run_command(
        self, command: str, cwd: Optional[str], timeout: float
    ) -> ActionResult:
        try:
            proc = await asyncio.create_subprocess_shell(
                command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=cwd or None,
            )
            try:
                stdout, stderr = await asyncio.wait_for(
                    proc.communicate(), timeout=timeout
                )
            except asyncio.TimeoutError:
                proc.kill()
                return ActionResult(success=False, error=f"Command timed out after {timeout}s")

            out = stdout.decode(errors="replace").strip()
            err = stderr.decode(errors="replace").strip()
            success = proc.returncode == 0
            return ActionResult(
                success  = success,
                output   = out or err or "(no output)",
                error    = err if not success else None,
                metadata = {"returncode": proc.returncode, "command": command[:200]},
            )
        except Exception as exc:
            return ActionResult(success=False, error=str(exc))

    # ------------------------------------------------------------------
    # Software install
    # ------------------------------------------------------------------

    async def _install_software(
        self, package: str, manager: Optional[str]
    ) -> ActionResult:
        if manager:
            managers = [manager]
        elif _PLATFORM == "Windows":
            managers = ["winget", "choco", "pip"]
        elif _PLATFORM == "Darwin":
            managers = ["brew", "pip3"]
        else:
            managers = ["apt", "pip3", "snap"]

        for mgr in managers:
            if shutil.which(mgr):
                cmd_map = {
                    "winget": f'winget install "{package}"',
                    "choco":  f"choco install {package} -y",
                    "brew":   f"brew install {package}",
                    "pip":    f"{sys.executable} -m pip install {package}",
                    "pip3":   f"pip3 install {package}",
                    "apt":    f"sudo apt-get install -y {package}",
                    "snap":   f"snap install {package}",
                }
                cmd = cmd_map.get(mgr, f"{mgr} install {package}")
                return await self._run_command(cmd, None, 300.0)

        return ActionResult(
            success=False,
            error=f"No supported package manager found. Tried: {managers}",
        )

    # ------------------------------------------------------------------
    # Clipboard
    # ------------------------------------------------------------------

    def _write_clipboard(self, text: str) -> ActionResult:
        if _CLIP_AVAILABLE:
            pyperclip.copy(text)
            return ActionResult(success=True, output=f"Copied {len(text)} chars to clipboard")
        # PowerShell fallback on Windows
        if _PLATFORM == "Windows":
            try:
                subprocess.run(
                    ["powershell", "-Command", f"Set-Clipboard -Value '{text}'"],
                    check=True, capture_output=True
                )
                return ActionResult(success=True, output="Copied to clipboard via PowerShell")
            except Exception as exc:
                return ActionResult(success=False, error=str(exc))
        return ActionResult(success=False, error="pyperclip not installed: pip install pyperclip")

    # ------------------------------------------------------------------
    # Process kill
    # ------------------------------------------------------------------

    def _kill_process(self, target: str, force: bool = False) -> ActionResult:
        import signal as sig

        # Numeric PID
        if target.isdigit():
            pid = int(target)
            try:
                os.kill(pid, sig.SIGTERM if not force else sig.SIGKILL)
                return ActionResult(success=True, output=f"Sent signal to PID {pid}")
            except Exception as exc:
                return ActionResult(success=False, error=str(exc))

        # Name-based
        if _PLATFORM == "Windows":
            flag = "/F" if force else ""
            result = subprocess.run(
                ["taskkill", flag, "/IM", target if target.endswith(".exe") else f"{target}.exe"],
                capture_output=True
            )
        else:
            signal = "-9" if force else "-15"
            result = subprocess.run(["pkill", signal, "-f", target], capture_output=True)

        if result.returncode == 0:
            return ActionResult(success=True, output=f"Killed process '{target}'")
        return ActionResult(success=False, error=f"Could not kill '{target}' (not found or permission denied)")

    # ------------------------------------------------------------------
    # Power control
    # ------------------------------------------------------------------

    def _system_shutdown(self, delay_seconds: int = 0) -> ActionResult:
        if _PLATFORM == "Windows":
            subprocess.Popen(["shutdown", "/s", "/t", str(delay_seconds)])
        elif _PLATFORM == "Darwin":
            subprocess.Popen(["sudo", "shutdown", "-h", f"+{delay_seconds // 60 or 'now'}"])
        else:
            subprocess.Popen(["sudo", "shutdown", "-h", f"+{delay_seconds // 60 or 'now'}"])
        return ActionResult(success=True, output=f"System shutdown initiated (delay: {delay_seconds}s)")

    def _system_restart(self, delay_seconds: int = 0) -> ActionResult:
        if _PLATFORM == "Windows":
            subprocess.Popen(["shutdown", "/r", "/t", str(delay_seconds)])
        elif _PLATFORM == "Darwin":
            subprocess.Popen(["sudo", "shutdown", "-r", f"+{delay_seconds // 60 or 'now'}"])
        else:
            subprocess.Popen(["sudo", "shutdown", "-r", f"+{delay_seconds // 60 or 'now'}"])
        return ActionResult(success=True, output=f"System restart initiated (delay: {delay_seconds}s)")

    # ------------------------------------------------------------------
    # Registry (Windows only)
    # ------------------------------------------------------------------

    def _modify_registry(
        self, key: str, value_name: str, value_data, value_type: str = "REG_SZ"
    ) -> ActionResult:
        if _PLATFORM != "Windows":
            return ActionResult(success=False, error="Registry modification only supported on Windows")
        try:
            import winreg
            type_map = {
                "REG_SZ":    winreg.REG_SZ,
                "REG_DWORD": winreg.REG_DWORD,
                "REG_QWORD": winreg.REG_QWORD,
                "REG_BINARY": winreg.REG_BINARY,
            }
            reg_type = type_map.get(value_type, winreg.REG_SZ)
            # Parse hive from key string (e.g., "HKCU\\Software\\...")
            hive_str, _, subkey = key.partition("\\")
            hive_map = {
                "HKCU": winreg.HKEY_CURRENT_USER,
                "HKEY_CURRENT_USER": winreg.HKEY_CURRENT_USER,
                "HKLM": winreg.HKEY_LOCAL_MACHINE,
                "HKEY_LOCAL_MACHINE": winreg.HKEY_LOCAL_MACHINE,
            }
            hive = hive_map.get(hive_str.upper())
            if not hive:
                return ActionResult(success=False, error=f"Unknown registry hive: {hive_str}")
            with winreg.OpenKey(hive, subkey, 0, winreg.KEY_WRITE) as reg_key:
                winreg.SetValueEx(reg_key, value_name, 0, reg_type, value_data)
            return ActionResult(success=True, output=f"Set {key}\\{value_name} = {value_data!r}")
        except Exception as exc:
            return ActionResult(success=False, error=str(exc))


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------

_executor: Optional[DesktopExecutor] = None

def get_desktop_executor() -> DesktopExecutor:
    global _executor
    if _executor is None:
        _executor = DesktopExecutor()
    return _executor
