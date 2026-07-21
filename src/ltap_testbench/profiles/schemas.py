from enum import StrEnum
from typing import ClassVar

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class RouterKindValue(StrEnum):
    MIKROTIK = "mikrotik"
    GENERIC = "generic"
    FAKE = "fake"


class Protocol(StrEnum):
    TCP = "tcp"
    UDP = "udp"


class UdpUploadPattern(StrEnum):
    AFTER_EACH_TCP = "after_each_tcp"
    BEGINNING = "beginning"
    END = "end"


class Stage(StrEnum):
    PREFLIGHT = "preflight"
    PATH_VERIFICATION = "path-verification"
    IDLE_LATENCY = "idle-latency"
    TCP_UPLOAD = "tcp-upload"
    UDP_UPLOAD = "udp-upload"
    VIDEO_UDP_PROBE = "video-udp-probe"


STAGE_ALIASES = {
    "short-upload": Stage.TCP_UPLOAD,
}


class PortRange(BaseModel):
    start: int = Field(ge=1, le=65535)
    end: int = Field(ge=1, le=65535)

    @model_validator(mode="after")
    def validate_order(self) -> "PortRange":
        if self.end < self.start:
            raise ValueError("port range end must be greater than or equal to start")
        return self

    def overlaps(self, other: "PortRange") -> bool:
        return self.start <= other.end and other.start <= self.end


class RouterPathConfig(BaseModel):
    id: str = Field(min_length=1, max_length=40, pattern=r"^[a-zA-Z0-9_.-]+$")
    label: str | None = None
    interface: str | None = None
    routing_table: str | None = None
    protocol: Protocol = Protocol.TCP
    ports: PortRange | None = None
    expected_public_ip: str | None = None
    metadata: dict = Field(default_factory=dict)


class RouterProfileConfig(BaseModel):
    slug: str = Field(min_length=1, max_length=80, pattern=r"^[a-z0-9][a-z0-9_.-]*$")
    display_name: str = Field(min_length=1, max_length=160)
    kind: RouterKindValue
    management_host: str | None = None
    management_protocol: str | None = None
    username: str | None = None
    secret_ref: str | None = None
    expected_gateway: str | None = None
    controller_interface: str | None = None
    allow_configuration_changes: bool = False
    paths: list[RouterPathConfig] = Field(default_factory=list)
    metadata: dict = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_router_profile(self) -> "RouterProfileConfig":
        path_ids = [path.id for path in self.paths]
        if len(path_ids) != len(set(path_ids)):
            raise ValueError("router path IDs must be unique")
        if self.kind == RouterKindValue.MIKROTIK and not self.management_host:
            raise ValueError("MikroTik profiles require management_host")
        if self.kind == RouterKindValue.GENERIC and len(self.paths) > 1:
            raise ValueError("generic router profiles support one logical path in the MVP")
        validate_non_overlapping_ports(self.paths)
        return self


class LatencyStageConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    duration_seconds: int = Field(default=60, ge=1)
    interval_ms: int = Field(default=100, ge=10)


class TcpUploadStageConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    duration_seconds: int = Field(default=30, ge=1)
    count: int = Field(default=1, ge=1, le=100)
    parallel_streams: list[int] = Field(default_factory=lambda: [1])
    payload_bytes: int | None = Field(default=None, ge=1)

    @model_validator(mode="after")
    def validate_parallel_streams(self) -> "TcpUploadStageConfig":
        if any(streams < 1 for streams in self.parallel_streams):
            raise ValueError("parallel stream counts must be positive")
        return self


class UdpUploadStageConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    duration_seconds: int = Field(default=30, ge=1)
    bitrate_mbit_s: float = Field(default=2.0, gt=0)
    datagram_bytes: int = Field(default=1200, ge=64, le=9000)
    pattern: UdpUploadPattern = UdpUploadPattern.END


class VideoProbeConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool = True
    duration_seconds: int = Field(default=30, ge=1, le=3600)
    bitrate_mbit_s: float = Field(default=5.0, gt=0, le=50)
    fps: int = Field(default=25, ge=1, le=120)
    resolution: str = Field(default="1080p", min_length=1, max_length=20)
    scenario: str = Field(default="city", min_length=1, max_length=40)
    payload_bytes: int = Field(default=1200, ge=300, le=9000)
    receiver_settle_seconds: int = Field(default=5, ge=0, le=30)
    traffic_seed: str = Field(default="video-trace-v1", min_length=1, max_length=80)
    trace_id: str = Field(default="synthetic-city-v1", min_length=1, max_length=120)
    generator_version: str = Field(default="synthetic-video-v2", min_length=1, max_length=80)


class TemporaryRouterChangesConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    disable_fasttrack: bool = False
    clear_test_connections: bool = True


class TestPlanConfig(BaseModel):
    __test__: ClassVar[bool] = False
    model_config = ConfigDict(extra="forbid")

    slug: str = Field(min_length=1, max_length=80, pattern=r"^[a-z0-9][a-z0-9_.-]*$")
    name: str = Field(min_length=1, max_length=160)
    version: str = Field(default="1", min_length=1, max_length=40)
    protocol_id: str = Field(default="exploratory-lab", min_length=1, max_length=80)
    protocol_version: str = Field(default="1", min_length=1, max_length=40)
    result_schema_version: int = Field(default=2, ge=1)
    server_slug: str | None = Field(default=None, min_length=1, max_length=80)
    stages: list[Stage] = Field(default_factory=list)
    latency: LatencyStageConfig = Field(default_factory=LatencyStageConfig)
    tcp_upload: TcpUploadStageConfig = Field(default_factory=TcpUploadStageConfig)
    udp_upload: UdpUploadStageConfig = Field(default_factory=UdpUploadStageConfig)
    video_probe: VideoProbeConfig = Field(default_factory=VideoProbeConfig)
    traffic: dict = Field(default_factory=dict)
    telemetry: dict = Field(default_factory=dict)
    metadata: dict = Field(default_factory=dict)
    temporary_router_changes: TemporaryRouterChangesConfig = Field(
        default_factory=TemporaryRouterChangesConfig
    )

    @field_validator("stages", mode="before")
    @classmethod
    def migrate_stage_aliases(cls, value: object) -> object:
        if not isinstance(value, list):
            return value
        return [STAGE_ALIASES.get(item, item) if isinstance(item, str) else item for item in value]

    @model_validator(mode="after")
    def validate_plan(self) -> "TestPlanConfig":
        if not self.stages:
            raise ValueError("test plan must include at least one stage")
        if len(self.stages) != len(set(self.stages)):
            raise ValueError("test plan stages must be unique")
        if (
            self.udp_upload.pattern == UdpUploadPattern.AFTER_EACH_TCP
            and Stage.TCP_UPLOAD not in self.stages
        ):
            raise ValueError("udp after_each_tcp pattern requires the tcp-upload stage")
        if self.tcp_upload.count != 1 and Stage.TCP_UPLOAD not in self.stages:
            raise ValueError("tcp upload count has no effect without the tcp-upload stage")
        if self.video_probe.enabled and Stage.VIDEO_UDP_PROBE not in self.stages:
            self.video_probe.enabled = False
        return self


class ServerProfileConfig(BaseModel):
    slug: str = Field(min_length=1, max_length=80, pattern=r"^[a-z0-9][a-z0-9_.-]*$")
    display_name: str = Field(min_length=1, max_length=160)
    control_api_url: str = Field(min_length=1, max_length=255)
    token_secret_ref: str | None = None
    public_host: str | None = None
    metadata: dict = Field(default_factory=dict)


def validate_non_overlapping_ports(paths: list[RouterPathConfig]) -> None:
    configured = [path for path in paths if path.ports is not None]
    for index, path in enumerate(configured):
        for other in configured[index + 1 :]:
            if (
                path.protocol == other.protocol
                and path.ports
                and other.ports
                and path.ports.overlaps(other.ports)
            ):
                raise ValueError(
                    f"port range for {path.id} overlaps {other.id} on protocol {path.protocol}"
                )
