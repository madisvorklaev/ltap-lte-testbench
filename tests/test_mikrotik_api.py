import pytest

from ltap_testbench.routers.mikrotik import RouterOsApi, RouterOsApiError, _routed_ping_rows


class FragmentedSocket:
    def __init__(self, chunks: list[bytes]) -> None:
        self.chunks = chunks
        self.sent = b""

    def recv(self, size: int) -> bytes:
        if not self.chunks:
            return b""
        chunk = self.chunks.pop(0)
        if len(chunk) > size:
            self.chunks.insert(0, chunk[size:])
            return chunk[:size]
        return chunk

    def sendall(self, data: bytes) -> None:
        self.sent += data


def sentence(*words: str) -> bytes:
    payload = b""
    for word in words:
        data = word.encode()
        payload += RouterOsApi._encode_len(len(data)) + data
    return payload + b"\0"


def test_routeros_api_reads_fragmented_sentences() -> None:
    api = RouterOsApi("198.51.100.1", "admin", "secret")
    api.sock = FragmentedSocket(
        [
            sentence("!re", "=name=r1")[:2],
            sentence("!re", "=name=r1")[2:5],
            sentence("!re", "=name=r1")[5:],
            sentence("!done"),
        ]
    )

    replies = api.command(["/system/identity/print"])

    assert RouterOsApi.rows(replies) == [{"name": "r1"}]


def test_routeros_api_raises_on_trap() -> None:
    api = RouterOsApi("198.51.100.1", "admin", "secret")
    api.sock = FragmentedSocket([sentence("!trap", "=message=no such route")])

    with pytest.raises(RuntimeError, match="no such route"):
        api.command(["/ping"])


def test_routed_ping_falls_back_to_routing_mark() -> None:
    class FakeApi:
        def __init__(self) -> None:
            self.commands = []

        def command(self, words: list[str]) -> list[list[str]]:
            self.commands.append(words)
            if any(word.startswith("=routing-table=") for word in words):
                raise RouterOsApiError(["!trap", "=message=unknown parameter routing-table"])
            return [
                [
                    "!re",
                    "=sent=1",
                    "=received=1",
                    "=avg-rtt=12ms",
                ],
                ["!done"],
            ]

        def rows(self, replies: list[list[str]]) -> list[dict[str, str]]:
            return RouterOsApi.rows(replies)

    api = FakeApi()

    rows, parameter, error = _routed_ping_rows(api, "198.51.100.10", 1, "to-lte1")

    assert parameter == "routing-mark"
    assert error is None
    assert rows == [{"sent": "1", "received": "1", "avg-rtt": "12ms"}]
    assert any("=routing-table=to-lte1" in command for command in api.commands)
    assert any("=routing-mark=to-lte1" in command for command in api.commands)


def test_routed_ping_falls_back_after_empty_routing_table_rows() -> None:
    class FakeApi:
        def __init__(self) -> None:
            self.commands = []

        def command(self, words: list[str]) -> list[list[str]]:
            self.commands.append(words)
            if any(word.startswith("=routing-table=") for word in words):
                return [["!done"]]
            return [
                [
                    "!re",
                    "=sent=1",
                    "=received=1",
                    "=avg-rtt=18ms",
                ],
                ["!done"],
            ]

        def rows(self, replies: list[list[str]]) -> list[dict[str, str]]:
            return RouterOsApi.rows(replies)

    api = FakeApi()

    rows, parameter, error = _routed_ping_rows(api, "198.51.100.10", 1, "to-lte1")

    assert parameter == "routing-mark"
    assert error is None
    assert rows == [{"sent": "1", "received": "1", "avg-rtt": "18ms"}]
    assert any("=routing-table=to-lte1" in command for command in api.commands)
    assert any("=routing-mark=to-lte1" in command for command in api.commands)


def test_routed_ping_keeps_non_parameter_trap_invalid() -> None:
    class FakeApi:
        def command(self, _words: list[str]) -> list[list[str]]:
            raise RouterOsApiError(["!trap", "=message=no route to host"])

        def rows(self, replies: list[list[str]]) -> list[dict[str, str]]:
            return RouterOsApi.rows(replies)

    rows, parameter, error = _routed_ping_rows(FakeApi(), "198.51.100.10", 1, "to-lte1")

    assert rows == []
    assert parameter == "routing-table"
    assert error == "no route to host"
