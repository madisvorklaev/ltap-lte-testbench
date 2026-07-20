import json
from dataclasses import dataclass
from numbers import Real


@dataclass(frozen=True)
class HttpUploadSummary:
    http_code: str | None
    time_total_seconds: float | None
    time_connect_seconds: float | None
    speed_upload_bytes_s: float | None
    size_upload_bytes: int | None
    remote_ip: str | None
    remote_port: int | None

    @property
    def speed_upload_mbit_s(self) -> float | None:
        if self.speed_upload_bytes_s is None:
            return None
        return self.speed_upload_bytes_s * 8 / 1_000_000


def parse_curl_write_out(output: str) -> HttpUploadSummary:
    data = json.loads(output or "{}")
    return HttpUploadSummary(
        http_code=data.get("http_code"),
        time_total_seconds=_float_or_none(data.get("time_total")),
        time_connect_seconds=_float_or_none(data.get("time_connect")),
        speed_upload_bytes_s=_float_or_none(data.get("speed_upload")),
        size_upload_bytes=_int_or_none(data.get("size_upload")),
        remote_ip=data.get("remote_ip"),
        remote_port=_int_or_none(data.get("remote_port")),
    )


def _float_or_none(value: object) -> float | None:
    if not isinstance(value, str | Real):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _int_or_none(value: object) -> int | None:
    if not isinstance(value, str | Real):
        return None
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None
