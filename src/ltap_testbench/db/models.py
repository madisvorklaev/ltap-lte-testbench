from datetime import datetime
from enum import StrEnum

from sqlalchemy import JSON, DateTime, Enum, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ltap_testbench.core.time import utc_now
from ltap_testbench.db.base import Base


class RouterKind(StrEnum):
    MIKROTIK = "mikrotik"
    GENERIC = "generic"
    FAKE = "fake"


class RunState(StrEnum):
    CREATED = "CREATED"
    QUEUED = "QUEUED"
    PREFLIGHT = "PREFLIGHT"
    AWAITING_CONFIRMATION = "AWAITING_CONFIRMATION"
    PREPARING_ROUTER = "PREPARING_ROUTER"
    VERIFYING_PATHS = "VERIFYING_PATHS"
    WARMING_UP = "WARMING_UP"
    RUNNING = "RUNNING"
    COOLING_DOWN = "COOLING_DOWN"
    ANALYZING = "ANALYZING"
    GENERATING_REPORT = "GENERATING_REPORT"
    RESTORING = "RESTORING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCEL_REQUESTED = "CANCEL_REQUESTED"
    CANCELLED = "CANCELLED"
    INTERRUPTED = "INTERRUPTED"
    RECOVERY_REQUIRED = "RECOVERY_REQUIRED"


class RouterProfile(Base):
    __tablename__ = "router_profiles"

    id: Mapped[int] = mapped_column(primary_key=True)
    slug: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    display_name: Mapped[str] = mapped_column(String(160))
    kind: Mapped[RouterKind] = mapped_column(Enum(RouterKind))
    management_host: Mapped[str | None] = mapped_column(String(255), nullable=True)
    management_protocol: Mapped[str | None] = mapped_column(String(40), nullable=True)
    username: Mapped[str | None] = mapped_column(String(120), nullable=True)
    secret_ref: Mapped[str | None] = mapped_column(String(255), nullable=True)
    expected_gateway: Mapped[str | None] = mapped_column(String(255), nullable=True)
    controller_interface: Mapped[str | None] = mapped_column(String(80), nullable=True)
    allow_configuration_changes: Mapped[bool] = mapped_column(default=False)
    metadata_json: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    runs: Mapped[list["TestRun"]] = relationship(back_populates="router")


class TestPlan(Base):
    __tablename__ = "test_plans"

    id: Mapped[int] = mapped_column(primary_key=True)
    slug: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(160))
    version: Mapped[str] = mapped_column(String(40), default="1")
    definition: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class ServerProfile(Base):
    __tablename__ = "server_profiles"

    id: Mapped[int] = mapped_column(primary_key=True)
    slug: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    display_name: Mapped[str] = mapped_column(String(160))
    control_api_url: Mapped[str] = mapped_column(String(255))
    token_secret_ref: Mapped[str | None] = mapped_column(String(255), nullable=True)
    public_host: Mapped[str | None] = mapped_column(String(255), nullable=True)
    metadata_json: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class TestRun(Base):
    __tablename__ = "test_runs"

    id: Mapped[int] = mapped_column(primary_key=True)
    run_id: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    router_id: Mapped[int] = mapped_column(ForeignKey("router_profiles.id"))
    plan_slug: Mapped[str] = mapped_column(String(80))
    state: Mapped[RunState] = mapped_column(Enum(RunState), default=RunState.CREATED)
    state_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    resolved_plan: Mapped[dict] = mapped_column(JSON, default=dict)
    summary: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    router: Mapped[RouterProfile] = relationship(back_populates="runs")
    events: Mapped[list["RunEvent"]] = relationship(
        back_populates="run",
        cascade="all, delete-orphan",
    )


class RunEvent(Base):
    __tablename__ = "run_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    run_pk: Mapped[int] = mapped_column(ForeignKey("test_runs.id"))
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    event_type: Mapped[str] = mapped_column(String(80))
    message: Mapped[str] = mapped_column(Text)
    details: Mapped[dict] = mapped_column(JSON, default=dict)

    run: Mapped[TestRun] = relationship(back_populates="events")
