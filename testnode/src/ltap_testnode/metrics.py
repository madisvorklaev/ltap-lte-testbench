import os
import shutil
import time
from dataclasses import asdict, dataclass
from pathlib import Path


@dataclass(frozen=True)
class NetworkInterfaceMetrics:
    name: str
    rx_bytes: int
    tx_bytes: int
    rx_errors: int
    tx_errors: int
    rx_drops: int
    tx_drops: int
    operstate: str | None
    carrier: bool | None
    speed_mbit_s: int | None


def _read_text(path: Path) -> str | None:
    try:
        return path.read_text().strip()
    except OSError:
        return None


def _read_int(path: Path) -> int | None:
    text = _read_text(path)
    if text is None:
        return None
    try:
        return int(text)
    except ValueError:
        return None


def boot_time_epoch() -> float | None:
    try:
        lines = Path("/proc/stat").read_text().splitlines()
    except OSError:
        return None
    for line in lines:
        if line.startswith("btime "):
            return float(line.split()[1])
    return None


def cpu_temperature_c() -> float | None:
    for temp_path in sorted(Path("/sys/class/thermal").glob("thermal_zone*/temp")):
        value = _read_int(temp_path)
        if value is not None:
            return value / 1000
    return None


def memory_info() -> dict[str, int]:
    values: dict[str, int] = {}
    try:
        lines = Path("/proc/meminfo").read_text().splitlines()
    except OSError:
        return values
    for line in lines:
        try:
            key, value = line.split(":", 1)
            values[key] = int(value.strip().split()[0]) * 1024
        except (ValueError, IndexError):
            continue
    return values


def network_interfaces() -> list[NetworkInterfaceMetrics]:
    interfaces: list[NetworkInterfaceMetrics] = []
    try:
        lines = Path("/proc/net/dev").read_text().splitlines()[2:]
    except OSError:
        return interfaces
    for line in lines:
        name, counters = line.split(":", 1)
        parts = counters.split()
        sysfs = Path("/sys/class/net") / name.strip()
        carrier_text = _read_text(sysfs / "carrier")
        speed = _read_int(sysfs / "speed")
        interfaces.append(
            NetworkInterfaceMetrics(
                name=name.strip(),
                rx_bytes=int(parts[0]),
                rx_errors=int(parts[2]),
                rx_drops=int(parts[3]),
                tx_bytes=int(parts[8]),
                tx_errors=int(parts[10]),
                tx_drops=int(parts[11]),
                operstate=_read_text(sysfs / "operstate"),
                carrier=None if carrier_text is None else carrier_text == "1",
                speed_mbit_s=speed if speed and speed > 0 else None,
            )
        )
    return interfaces


def collect_metrics() -> dict:
    disk = shutil.disk_usage("/")
    boot_time = boot_time_epoch()
    uptime = None if boot_time is None else max(0.0, time.time() - boot_time)
    load1, load5, load15 = os.getloadavg()
    mem = memory_info()
    return {
        "boot_time_epoch": boot_time,
        "uptime_seconds": uptime,
        "load_average": {"1m": load1, "5m": load5, "15m": load15},
        "cpu_temperature_c": cpu_temperature_c(),
        "memory": {
            "total_bytes": mem.get("MemTotal"),
            "available_bytes": mem.get("MemAvailable"),
        },
        "disk": {
            "total_bytes": disk.total,
            "used_bytes": disk.used,
            "free_bytes": disk.free,
        },
        "network": [asdict(interface) for interface in network_interfaces()],
    }
