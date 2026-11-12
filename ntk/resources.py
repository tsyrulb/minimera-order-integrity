"""Small Linux memory guard; never terminates unrelated processes."""

from pathlib import Path
from typing import TypedDict

from .contracts import AppError

MIB = 1024 * 1024
MEMORY_FLOOR_MIB = 1536
MODEL_LOAD_BUDGET_MIB = 1400


class MemoryState(TypedDict):
    available_mib: int | None
    total_mib: int | None
    swap_used_mib: int | None
    pressure_avg10: float | None
    floor_mib: int


def model_load_budget(model: str, size_bytes: int | float | None) -> int:
    measured = {"qwen2.5:1.5b": 1400, "qwen2.5:3b": 2400}
    if model in measured:
        return measured[model]
    if isinstance(size_bytes, bool) or not isinstance(size_bytes, (int, float)) or size_bytes <= 0:
        raise AppError(
            "MODEL_SIZE_UNKNOWN",
            "Local model size is unknown. Inference is paused to protect memory.",
        )
    # Unknown models do not inherit the small model's optimistic allowance.
    return max(1400, round(size_bytes / MIB * 1.5 + 512))


def memory_snapshot() -> MemoryState:
    try:
        values = {}
        for line in Path("/proc/meminfo").read_text().splitlines():
            key, raw = line.split(":", 1)
            values[key] = int(raw.strip().split()[0]) * 1024
        available = values["MemAvailable"]
        total = values["MemTotal"]
        # A container's host-wide MemAvailable alone can overstate its budget.
        maximum = Path("/sys/fs/cgroup/memory.max")
        current = Path("/sys/fs/cgroup/memory.current")
        if maximum.exists() and current.exists() and maximum.read_text().strip() != "max":
            limit = int(maximum.read_text())
            available = min(available, max(0, limit - int(current.read_text())))
            total = min(total, limit)
        pressure = 0.0
        psi = Path("/proc/pressure/memory")
        if psi.exists():
            for line in psi.read_text().splitlines():
                if line.startswith("some "):
                    pressure = float(dict(x.split("=") for x in line.split()[1:])["avg10"])
        return {
            "available_mib": round(available / MIB),
            "total_mib": round(total / MIB),
            "swap_used_mib": round((values["SwapTotal"] - values["SwapFree"]) / MIB),
            "pressure_avg10": pressure,
            "floor_mib": MEMORY_FLOOR_MIB,
        }
    except (OSError, KeyError, ValueError):
        return {
            "available_mib": None,
            "total_mib": None,
            "swap_used_mib": None,
            "pressure_avg10": None,
            "floor_mib": MEMORY_FLOOR_MIB,
        }


def ensure_memory(
    loaded: bool = False, load_budget_mib: int = MODEL_LOAD_BUDGET_MIB
) -> MemoryState:
    state = memory_snapshot()
    if state["available_mib"] is None or state["pressure_avg10"] is None:
        raise AppError(
            "MEMORY_UNKNOWN",
            "Local inference requires readable memory statistics. Use Linux or a remote provider.",
        )
    required = MEMORY_FLOOR_MIB + (0 if loaded else load_budget_mib)
    if state["available_mib"] < required or state["pressure_avg10"] >= 5:
        raise AppError(
            "MEMORY_GUARD",
            "Inference paused to preserve at least 1.5 GiB of available memory. Close an unused app, then retry.",
            503,
        )
    return state
