import os
import re
import socket

from ltap_testbench.routers.base import RouterAdapter, RouterCheck


class RouterOsApi:
    def __init__(self, host: str, user: str, password: str, port: int = 8728, timeout: int = 10):
        self.host = host
        self.user = user
        self.password = password
        self.port = port
        self.timeout = timeout
        self.sock: socket.socket | None = None

    def __enter__(self) -> "RouterOsApi":
        self.sock = socket.create_connection((self.host, self.port), timeout=self.timeout)
        self.command(["/login", f"=name={self.user}", f"=password={self.password}"])
        return self

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
        if self.sock:
            self.sock.close()

    @staticmethod
    def _encode_len(length: int) -> bytes:
        if length < 0x80:
            return bytes([length])
        if length < 0x4000:
            return bytes([(length >> 8) | 0x80, length & 0xFF])
        if length < 0x200000:
            return bytes([(length >> 16) | 0xC0, (length >> 8) & 0xFF, length & 0xFF])
        if length < 0x10000000:
            return bytes(
                [
                    (length >> 24) | 0xE0,
                    (length >> 16) & 0xFF,
                    (length >> 8) & 0xFF,
                    length & 0xFF,
                ]
            )
        return bytes(
            [
                0xF0,
                (length >> 24) & 0xFF,
                (length >> 16) & 0xFF,
                (length >> 8) & 0xFF,
                length & 0xFF,
            ]
        )

    def _decode_len(self) -> int:
        if self.sock is None:
            raise RuntimeError("RouterOS API socket is not connected")
        first = self._recv_exact(1)
        byte = first[0]
        if (byte & 0x80) == 0:
            return byte
        if (byte & 0xC0) == 0x80:
            return ((byte & ~0xC0) << 8) | self._recv_exact(1)[0]
        if (byte & 0xE0) == 0xC0:
            data = self._recv_exact(2)
            return ((byte & ~0xE0) << 16) | (data[0] << 8) | data[1]
        if (byte & 0xF0) == 0xE0:
            data = self._recv_exact(3)
            return ((byte & ~0xF0) << 24) | (data[0] << 16) | (data[1] << 8) | data[2]
        data = self._recv_exact(4)
        return (data[0] << 24) | (data[1] << 16) | (data[2] << 8) | data[3]

    def _recv_exact(self, length: int) -> bytes:
        if self.sock is None:
            raise RuntimeError("RouterOS API socket is not connected")
        data = b""
        while len(data) < length:
            chunk = self.sock.recv(length - len(data))
            if not chunk:
                raise EOFError("RouterOS API closed the connection")
            data += chunk
        return data

    def _write_word(self, word: str) -> None:
        if self.sock is None:
            raise RuntimeError("RouterOS API socket is not connected")
        data = word.encode()
        self.sock.sendall(self._encode_len(len(data)) + data)

    def _read_sentence(self) -> list[str]:
        words: list[str] = []
        while True:
            length = self._decode_len()
            if length == 0:
                return words
            data = self._recv_exact(length)
            words.append(data.decode(errors="replace"))

    def command(self, words: list[str]) -> list[list[str]]:
        for word in words:
            self._write_word(word)
        self._write_word("")
        replies: list[list[str]] = []
        while True:
            sentence = self._read_sentence()
            replies.append(sentence)
            if sentence and sentence[0] in ("!done", "!fatal", "!trap"):
                if sentence[0] in {"!fatal", "!trap"}:
                    raise RuntimeError(sentence)
                return replies

    @staticmethod
    def rows(replies: list[list[str]]) -> list[dict[str, str]]:
        parsed = []
        for sentence in replies:
            if not sentence or sentence[0] != "!re":
                continue
            row = {}
            for word in sentence[1:]:
                if word.startswith("="):
                    key, value = word[1:].split("=", 1)
                    row[key] = value
            parsed.append(row)
        return parsed


class MikroTikRouterAdapter(RouterAdapter):
    def _secret(self) -> str | None:
        ref = self.profile.secret_ref
        if not ref:
            return None
        if ref.startswith("env:"):
            return os.environ.get(ref.removeprefix("env:"))
        return os.environ.get(ref)

    def _api(self) -> RouterOsApi:
        password = self._secret()
        if not password:
            raise RuntimeError("MikroTik password secret is not available")
        return RouterOsApi(
            self.profile.management_host or "",
            self.profile.username or "admin",
            password,
        )

    def _paths(self) -> list[dict]:
        paths = self.profile.metadata_json.get("paths", [])
        return paths if isinstance(paths, list) else []

    def preflight(self) -> list[RouterCheck]:
        if not self.profile.management_host:
            return [RouterCheck("management-host", False, "MikroTik profile has no host.", {})]
        try:
            with self._api() as api:
                identity = api.rows(api.command(["/system/identity/print"]))
                resource = api.rows(api.command(["/system/resource/print"]))
                interfaces = api.rows(api.command(["/interface/print", "=detail="]))
                lte = api.rows(api.command(["/interface/lte/print", "=detail="]))
        except Exception as exc:
            return [
                RouterCheck(
                    "mikrotik-api",
                    False,
                    f"MikroTik API discovery failed: {exc}",
                    {"host": self.profile.management_host, "type": type(exc).__name__},
                )
            ]

        checks = [
            RouterCheck(
                "mikrotik-api",
                True,
                "MikroTik API read-only discovery succeeded.",
                {
                    "host": self.profile.management_host,
                    "identity": identity[0].get("name") if identity else None,
                    "resource": resource[0] if resource else {},
                },
            )
        ]
        interface_names = {row.get("name") for row in interfaces}
        lte_names = {row.get("name") for row in lte}
        for path in self._paths():
            interface = path.get("interface") or path.get("id")
            ok = interface in interface_names and interface in lte_names
            checks.append(
                RouterCheck(
                    f"path-interface-{interface}",
                    ok,
                    f"LTE interface {interface} is present."
                    if ok
                    else f"LTE interface {interface} is missing.",
                    {"interface": interface},
                )
            )
        return checks

    def verify_paths(self) -> list[RouterCheck]:
        try:
            with self._api() as api:
                interfaces = api.rows(api.command(["/interface/print", "=detail="]))
                routes = api.rows(api.command(["/ip/route/print", "=detail="]))
                monitors = {}
                for path in self._paths():
                    interface = path.get("interface") or path.get("id")
                    rows = api.rows(
                        api.command(["/interface/lte/monitor", f"=numbers={interface}", "=once="])
                    )
                    monitors[interface] = rows[0] if rows else {}
        except Exception as exc:
            return [
                RouterCheck(
                    "mikrotik-path-verification",
                    False,
                    f"MikroTik path verification failed: {exc}",
                    {"type": type(exc).__name__},
                )
            ]

        by_name = {row.get("name"): row for row in interfaces}
        checks = []
        for path in self._paths():
            interface = path.get("interface") or path.get("id")
            routing_table = path.get("routing_table")
            row = by_name.get(interface, {})
            monitor = monitors.get(interface, {})
            status = monitor.get("status") or monitor.get("registration-status")
            route_ok = True
            matching_routes = []
            if routing_table:
                matching_routes = [
                    route
                    for route in routes
                    if route.get("gateway") == interface
                    and route.get("routing-table") == routing_table
                    and route.get("active") == "true"
                    and route.get("disabled") != "true"
                ]
                route_ok = bool(matching_routes)
            ok = (
                bool(row)
                and row.get("disabled") != "true"
                and row.get("running") == "true"
                and status in {"registered", "connected"}
                and route_ok
            )
            checks.append(
                RouterCheck(
                    f"path-{interface}",
                    ok,
                    (
                        f"{interface} is {status}; route table check "
                        f"{'passed' if route_ok else 'failed'}."
                    ),
                    {
                        "interface": interface,
                        "routing_table": routing_table,
                        "running": row.get("running"),
                        "disabled": row.get("disabled"),
                        "status": status,
                        "operator": monitor.get("current-operator"),
                        "primary_band": monitor.get("primary-band"),
                        "rsrp": monitor.get("rsrp"),
                        "rsrq": monitor.get("rsrq"),
                        "sinr": monitor.get("sinr"),
                        "matching_routes": matching_routes,
                    },
                )
            )
        return checks

    def collect_path_telemetry(self) -> list[dict]:
        rows = []
        with self._api() as api:
            for path in self._paths():
                interface = path.get("interface") or path.get("id")
                lte_monitor = api.rows(
                    api.command(["/interface/lte/monitor", f"=numbers={interface}", "=once="])
                )
                traffic = api.rows(
                    api.command(["/interface/monitor-traffic", f"=interface={interface}", "=once="])
                )
                monitor = lte_monitor[0] if lte_monitor else {}
                counters = traffic[0] if traffic else {}
                rows.append(
                    {
                        "path_id": path.get("id"),
                        "interface": interface,
                        "routing_table": path.get("routing_table"),
                        "status": monitor.get("status") or monitor.get("registration-status"),
                        "operator": monitor.get("current-operator"),
                        "access_technology": monitor.get("access-technology"),
                        "primary_band": monitor.get("primary-band"),
                        "ca_band": monitor.get("ca-band"),
                        "earfcn": monitor.get("earfcn"),
                        "rsrp": monitor.get("rsrp"),
                        "rsrq": monitor.get("rsrq"),
                        "sinr": monitor.get("sinr"),
                        "rssi": monitor.get("rssi"),
                        "tx_rate": counters.get("tx-bits-per-second"),
                        "rx_rate": counters.get("rx-bits-per-second"),
                        "tx_packets": counters.get("tx-packets-per-second"),
                        "rx_packets": counters.get("rx-packets-per-second"),
                    }
                )
        return rows

    def measure_latency(self, target_host: str, count: int = 5) -> list[dict]:
        results = []
        count = max(1, min(count, 50))
        with self._api() as api:
            for path in self._paths():
                path_id = path.get("id")
                routing_table = path.get("routing_table")
                rows = []
                routed = False
                if routing_table:
                    rows = api.rows(
                        api.command(
                            [
                                "/ping",
                                f"=address={target_host}",
                                f"=count={count}",
                                f"=routing-table={routing_table}",
                            ]
                        )
                    )
                    routed = bool(rows)
                samples = [_routeros_duration_to_ms(row.get("time")) for row in rows]
                samples = [sample for sample in samples if sample is not None]
                last = rows[-1] if rows else {}
                received = _int_or_zero(last.get("received"))
                sent = _int_or_zero(last.get("sent")) or count
                results.append(
                    {
                        "path_id": path_id,
                        "target_host": target_host,
                        "routing_table": routing_table,
                        "routing_table_used": routed,
                        "validity": "path-routed" if routed else "invalid",
                        "error": None if routed else "routed ping returned no rows",
                        "sent": sent,
                        "received": received,
                        "loss_percent": _float_or_none(last.get("packet-loss")),
                        "avg_ms": _routeros_duration_to_ms(last.get("avg-rtt")),
                        "min_ms": _routeros_duration_to_ms(last.get("min-rtt")),
                        "max_ms": _routeros_duration_to_ms(last.get("max-rtt")),
                        "samples_ms": samples,
                    }
                )
        return results


def _routeros_duration_to_ms(value: str | None) -> float | None:
    if not value:
        return None
    total = 0.0
    for number, unit in re.findall(r"(\d+(?:\.\d+)?)([a-z]+)", value):
        amount = float(number)
        if unit == "s":
            total += amount * 1000
        elif unit == "ms":
            total += amount
        elif unit == "us":
            total += amount / 1000
        elif unit == "ns":
            total += amount / 1_000_000
    return total if total else None


def _float_or_none(value: str | None) -> float | None:
    if value is None:
        return None
    cleaned = value.removesuffix("%")
    try:
        return float(cleaned)
    except ValueError:
        return None


def _int_or_zero(value: str | None) -> int:
    try:
        return int(value or 0)
    except ValueError:
        return 0
