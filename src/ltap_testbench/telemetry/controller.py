import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path


@dataclass(frozen=True)
class InterfaceState:
    name: str
    carrier: bool | None
    operstate: str | None


@dataclass(frozen=True)
class ControllerPreflight:
    default_route_interface: str | None
    expected_interface: str | None
    interface_states: list[InterfaceState]
    warnings: list[str]

    def to_dict(self) -> dict:
        data = asdict(self)
        data["interface_states"] = [asdict(item) for item in self.interface_states]
        return data


def _read_optional(path: Path) -> str | None:
    try:
        return path.read_text().strip()
    except OSError:
        return None


def default_route_interface() -> str | None:
    proc = subprocess.run(
        ["ip", "route", "show", "default"],
        check=False,
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        return None
    words = proc.stdout.split()
    if "dev" not in words:
        return None
    return words[words.index("dev") + 1]


def collect_interface_states() -> list[InterfaceState]:
    states: list[InterfaceState] = []
    for path in sorted(Path("/sys/class/net").iterdir()):
        carrier_text = _read_optional(path / "carrier")
        carrier = None if carrier_text is None else carrier_text == "1"
        states.append(
            InterfaceState(
                name=path.name,
                carrier=carrier,
                operstate=_read_optional(path / "operstate"),
            )
        )
    return states


def common_preflight(expected_interface: str | None = None) -> ControllerPreflight:
    route_iface = default_route_interface()
    states = collect_interface_states()
    warnings: list[str] = []
    if expected_interface and route_iface != expected_interface:
        warnings.append(
            f"default route uses {route_iface or 'unknown'} "
            f"instead of expected {expected_interface}"
        )
    if route_iface and route_iface.startswith(("wl", "wlan")):
        warnings.append(
            "default route appears to use Wi-Fi; live LTE router tests would be invalid"
        )
    return ControllerPreflight(
        default_route_interface=route_iface,
        expected_interface=expected_interface,
        interface_states=states,
        warnings=warnings,
    )
