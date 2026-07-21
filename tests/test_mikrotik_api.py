import pytest

from ltap_testbench.routers.mikrotik import RouterOsApi


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
