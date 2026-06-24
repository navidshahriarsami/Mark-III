"""
MARK III Reflex — System Module

Handles: time, date, uptime, CPU, RAM, GPU, disk, battery, temperature.
All data is local. Zero LLM calls. Zero internet.
"""
from __future__ import annotations

import datetime
import re
import time
from typing import Optional


# ─────────────────────────────────────────────────────────────────
# Evaluation guard — queries asking "is X normal/safe/okay?" should
# go to Qwen for reasoning, not return raw data from reflex.
# ─────────────────────────────────────────────────────────────────

_EVALUATION_RE = re.compile(
    r"\b(is (that|this|it) (normal|okay|ok|good|bad|fine|safe|dangerous|high|low|typical|expected|alright|worrying|concerning))"
    r"|\b(normal|typical|expected|safe|dangerous|concerning|worrying|okay|fine) (for|temp|temperature|gpu|cpu|ram|memory)"
    r"|\b(should (i|we) (worry|be worried|be concerned))"
    r"|\b(is|are) (the|my|that|this) (temp|temperature|gpu|cpu|reading) (normal|okay|ok|good|bad|safe|high|low|fine|dangerous)",
    re.I,
)


# ─────────────────────────────────────────────────────────────────
# Patterns → handler method name
# ─────────────────────────────────────────────────────────────────

_PATTERNS: list[tuple[re.Pattern, str]] = [
    # Time
    (re.compile(r"\bwhat('?s| is) (the )?time\b|\bwhat time is it\b|\bcurrent time\b|\btime now\b", re.I), "time"),
    # Date / day
    (re.compile(r"\bwhat('?s| is) (the |today'?s )?date\b|\bwhat day is (it|today)\b|\btoday'?s date\b|\bwhat month\b", re.I), "date"),
    # CPU
    (re.compile(r"\bcpu\b.*\b(usage|load|busy|percent|status)\b|\bhow busy is (the )?cpu\b|\bprocessor (usage|load)\b", re.I), "cpu"),
    # RAM / memory
    (re.compile(r"\b(how much |my )?(ram|memory) (usage|left|free|used|status|available)\b|\bmemory usage\b|\bram\b", re.I), "ram"),
    # GPU
    (re.compile(r"\bgpu\b|\bgraphics (card|usage|memory)\b|\bvram\b", re.I), "gpu"),
    # Disk / storage
    (re.compile(r"\b(disk|storage|drive|ssd|hdd)\b.*(space|usage|left|free|available|remain)\b|\bhow much storage\b", re.I), "disk"),
    # Battery
    (re.compile(r"\bbattery\b|\bhow (charged|much power|much battery)\b|\bpower level\b", re.I), "battery"),
    # Temperature — CPU and/or GPU
    (re.compile(r"\b(cpu|gpu|system)? ?(temperature|temp)\b|\bhow hot (is|are)\b|\boverheating\b|\btemps?\b", re.I), "temperature"),
    # Uptime
    (re.compile(r"\buptime\b|\bhow long (have you|has mark) been (running|up|on)\b|\bsystem uptime\b", re.I), "uptime"),
]


def can_handle(text: str) -> bool:
    # Reject evaluation/reasoning queries — let Qwen answer "is X normal?"
    if _EVALUATION_RE.search(text):
        return False
    return any(p.search(text) for p, _ in _PATTERNS)


def handle(text: str) -> Optional[str]:
    for pattern, method in _PATTERNS:
        if pattern.search(text):
            fn = globals().get(f"_get_{method}")
            if fn:
                return fn()
    return None


# ─────────────────────────────────────────────────────────────────
# Handlers
# ─────────────────────────────────────────────────────────────────

def _get_time() -> str:
    now = datetime.datetime.now()
    return f"It's {now.strftime('%I:%M %p').lstrip('0')}."


def _get_date() -> str:
    now = datetime.datetime.now()
    return f"Today is {now.strftime('%A, %B %d')}."


def _get_cpu() -> str:
    try:
        import psutil
        pct = psutil.cpu_percent(interval=0.3)
        return f"CPU is at {pct:.0f} percent."
    except ImportError:
        return "psutil not installed — CPU data unavailable."


def _get_ram() -> str:
    try:
        import psutil
        vm   = psutil.virtual_memory()
        used = vm.used / 1e9
        total = vm.total / 1e9
        pct  = vm.percent
        return f"RAM is at {pct:.0f} percent — {used:.1f} of {total:.1f} GB used."
    except ImportError:
        return "psutil not installed — RAM data unavailable."


def _get_gpu() -> str:
    # Primary: GPUtil (load, VRAM, temp from nvidia-smi)
    try:
        import GPUtil
        gpus = GPUtil.getGPUs()
        if not gpus:
            return "No GPU detected."
        parts = []
        for g in gpus:
            mem_pct = (g.memoryUsed / g.memoryTotal * 100) if g.memoryTotal else 0
            # Enrich with hot-spot temp from LHM DLL if available
            hotspot = ""
            try:
                lhm = _read_lhm_temps()
                hs = {k: v for k, v in lhm.items() if "hot spot" in k.lower() or "hotspot" in k.lower()}
                if hs:
                    hotspot = f", hot spot {list(hs.values())[0]:.0f}°C"
            except Exception:
                pass
            parts.append(
                f"{g.name}: {g.load * 100:.0f}% load, "
                f"{g.memoryUsed:.0f}/{g.memoryTotal:.0f} MB VRAM ({mem_pct:.0f}%), "
                f"{g.temperature:.0f}°C core{hotspot}"
            )
        return "GPU — " + " | ".join(parts) + "."
    except ImportError:
        return "GPUtil not installed."
    except Exception as e:
        return f"GPU data unavailable: {e}"


def _get_disk() -> str:
    try:
        import psutil
        d = psutil.disk_usage("C:\\")
        free  = d.free  / 1e9
        total = d.total / 1e9
        pct   = d.percent
        return f"C drive is {pct:.0f} percent full — {free:.0f} GB free of {total:.0f} GB."
    except ImportError:
        return "psutil not installed — disk data unavailable."


def _get_battery() -> str:
    try:
        import psutil
        b = psutil.sensors_battery()
        if b is None:
            return "No battery detected — this appears to be a desktop."
        status = "charging" if b.power_plugged else "on battery"
        return f"Battery at {b.percent:.0f} percent, {status}."
    except ImportError:
        return "psutil not installed — battery data unavailable."


_LHM_DIR = r"C:\Users\Celluloid Solutions\AppData\Local\LibreHardwareMonitor"


def _read_lhm_temps() -> dict[str, float]:
    """
    Read CPU and GPU temperatures directly from LibreHardwareMonitorLib.dll
    via pythonnet (no WMI, no service required).
    CPU temps require admin (ring-0 MSR access); GPU temps work without admin.
    Returns dict of {label: celsius}.
    """
    import sys, os
    if _LHM_DIR not in sys.path:
        sys.path.insert(0, _LHM_DIR)
    import clr
    clr.AddReference("LibreHardwareMonitorLib")
    from LibreHardwareMonitor.Hardware import Computer, SensorType

    c = Computer()
    c.IsCpuEnabled         = True
    c.IsGpuEnabled         = True
    c.IsMotherboardEnabled = True
    c.Open()

    results: dict[str, float] = {}
    try:
        for hw in c.Hardware:
            hw.Update()
            for sensor in hw.Sensors:
                if sensor.SensorType == SensorType.Temperature and sensor.Value is not None:
                    val = float(str(sensor.Value))
                    if val > 0:
                        results[f"{hw.Name} — {sensor.Name}"] = val
    finally:
        c.Close()
    return results


def _get_temperature() -> str:
    parts: list[str] = []

    # ── Direct DLL read (LibreHardwareMonitorLib.dll via pythonnet) ───
    try:
        temps = _read_lhm_temps()
        cpu_temps = {k: v for k, v in temps.items() if "core" in k.lower() and "gpu" not in k.lower()}
        gpu_temps = {k: v for k, v in temps.items() if "gpu" in k.lower()}

        if cpu_temps:
            avg_cpu = sum(cpu_temps.values()) / len(cpu_temps)
            parts.append(f"CPU {avg_cpu:.0f}°C")
        else:
            parts.append("CPU temp unavailable (run MARK III as admin for CPU sensors)")

        for label, val in gpu_temps.items():
            short = label.split("—")[-1].strip()
            parts.append(f"GPU {short} {val:.0f}°C")

        if parts:
            return "Temperatures — " + ", ".join(parts) + "."
    except ImportError:
        pass   # pythonnet not installed
    except Exception as e:
        pass   # DLL read failed — fall through to GPUtil

    # ── Fallback: GPUtil for GPU only ─────────────────────────────────
    try:
        import GPUtil
        gpus = GPUtil.getGPUs()
        for g in gpus:
            parts.append(f"GPU {g.temperature:.0f}°C")
        parts.insert(0, "CPU temp unavailable (needs admin)")
        return "Temperatures — " + ", ".join(parts) + "."
    except Exception:
        pass

    return "Temperature data unavailable."


def _get_uptime() -> str:
    try:
        import psutil
        boot = psutil.boot_time()
        elapsed = time.time() - boot
        hours   = int(elapsed // 3600)
        minutes = int((elapsed % 3600) // 60)
        if hours >= 1:
            return f"System has been running for {hours} hour{'s' if hours != 1 else ''} and {minutes} minute{'s' if minutes != 1 else ''}."
        return f"System has been running for {minutes} minute{'s' if minutes != 1 else ''}."
    except ImportError:
        return "psutil not installed — uptime unavailable."
