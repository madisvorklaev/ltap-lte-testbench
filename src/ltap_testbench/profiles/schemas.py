from enum import StrEnum
from typing import ClassVar

from pydantic import BaseModel, Field, model_validator


class RouterKindValue(StrEnum):
    MIKROTIK = "mikrotik"
    GENERIC = "generic"
    FAKE = "fake"


class Protocol(StrEnum):
    TCP = "tcp"
    UDP = "udp"


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
    duration_seconds: int = Field(default=60, ge=1)
    interval_ms: int = Field(default=100, ge=10)


class TcpUploadStageConfig(BaseModel):
    duration_seconds: int = Field(default=30, ge=1)
    parallel_streams: list[int] = Field(default_factory=lambda: [1])

    @model_validator(mode="after")
    def validate_parallel_streams(self) -> "TcpUploadStageConfig":
        if any(streams < 1 for streams in self.parallel_streams):
            raise ValueError("parallel stream counts must be positive")
        return self


class TemporaryRouterChangesConfig(BaseModel):
    disable_fasttrack: bool = False
    clear_test_connections: bool = True


class TestPlanConfig(BaseModel):
    __test__: ClassVar[bool] = False

    slug: str = Field(min_length=1, max_length=80, pattern=r"^[a-z0-9][a-z0-9_.-]*$")
    name: str = Field(min_length=1, max_length=160)
    version: str = Field(default="1", min_length=1, max_length=40)
    stages: list[str] = Field(default_factory=list)
    latency: LatencyStageConfig = Field(default_factory=LatencyStageConfig)
    tcp_upload: TcpUploadStageConfig = Field(default_factory=TcpUploadStageConfig)
    telemetry: dict = Field(default_factory=dict)
    temporary_router_changes: TemporaryRouterChangesConfig = Field(
        default_factory=TemporaryRouterChangesConfig
    )

    @model_validator(mode="after")
    def validate_plan(self) -> "TestPlanConfig":
        if not self.stages:
            raise ValueError("test plan must include at least one stage")
        if len(self.stages) != len(set(self.stages)):
            raise ValueError("test plan stages must be unique")
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
