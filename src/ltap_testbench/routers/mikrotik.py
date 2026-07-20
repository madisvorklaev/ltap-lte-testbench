import os
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
        first = self.sock.recv(1)
        if not first:
            raise EOFError("RouterOS API closed the connection")
        byte = first[0]
        if (byte & 0x80) == 0:
            return byte
        if (byte & 0xC0) == 0x80:
            return ((byte & ~0xC0) << 8) | self.sock.recv(1)[0]
        if (byte & 0xE0) == 0xC0:
            data = self.sock.recv(2)
            return ((byte & ~0xE0) << 16) | (data[0] << 8) | data[1]
        if (byte & 0xF0) == 0xE0:
            data = self.sock.recv(3)
            return ((byte & ~0xF0) << 24) | (data[0] << 16) | (data[1] << 8) | data[2]
        data = self.sock.recv(4)
        return (data[0] << 24) | (data[1] << 16) | (data[2] << 8) | data[3]

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
            if self.sock is None:
                raise RuntimeError("RouterOS API socket is not connected")
            data = b""
            while len(data) < length:
                data += self.sock.recv(length - len(data))
            words.append(data.decode(errors="replace"))

    def command(self, words: list[str]) -> list[list[str]]:
        for word in words:
            self._write_word(word)
        self._write_word("")
        replies: list[list[str]] = []
        while True:
            sentence = self._read_sentence()
            replies.append(sentence)
            if sentence and sentence[0] in ("!done", "!fatal"):
                if sentence[0] == "!fatal":
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
            if routing_table:
                route_ok = any(
                    route.get("gateway") == interface and routing_table in route.get("comment", "")
                    for route in routes
                )
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
                    },
                )
            )
        return checks
