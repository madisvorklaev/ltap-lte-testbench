from datetime import datetime
from enum import StrEnum

from sqlalchemy import JSON, Boolean, DateTime, Enum, Float, ForeignKey, Integer, String, Text
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


class ProtocolStatus(StrEnum):
    DRAFT = "draft"
    FROZEN = "frozen"
    RETIRED = "retired"


class GainSource(StrEnum):
    MANUFACTURER = "manufacturer"
    MEASURED = "measured"
    ESTIMATED = "estimated"
    UNKNOWN = "unknown"


class ComparisonDimension(StrEnum):
    FIRMWARE = "firmware"
    ROUTERBOOT = "routerboot"
    MODEM_MODEL = "modem_model"
    MODEM_FIRMWARE = "modem_firmware"
    ANTENNA = "antenna"
    GENERAL_REPEATABILITY = "general_repeatability"


class BatchState(StrEnum):
    DRAFT = "DRAFT"
    SCHEDULED = "SCHEDULED"
    RUNNING = "RUNNING"
    PAUSE_REQUESTED = "PAUSE_REQUESTED"
    PAUSED = "PAUSED"
    CANCEL_REQUESTED = "CANCEL_REQUESTED"
    CANCELLED = "CANCELLED"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class BatchAttemptState(StrEnum):
    PLANNED = "PLANNED"
    WAITING_FOR_START = "WAITING_FOR_START"
    CHECKING_PRECONDITIONS = "CHECKING_PRECONDITIONS"
    RUNNING = "RUNNING"
    VALID = "VALID"
    INVALID = "INVALID"
    FAILED = "FAILED"
    SKIPPED = "SKIPPED"
    CANCELLED = "CANCELLED"


class BenchmarkProtocol(Base):
    __tablename__ = "benchmark_protocols"

    id: Mapped[int] = mapped_column(primary_key=True)
    slug: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    version: Mapped[str] = mapped_column(String(40))
    name: Mapped[str] = mapped_column(String(160))
    definition_json: Mapped[dict] = mapped_column(JSON, default=dict)
    protocol_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    result_schema_version: Mapped[int] = mapped_column(default=2)
    status: Mapped[ProtocolStatus] = mapped_column(Enum(ProtocolStatus))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    frozen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class AntennaProfile(Base):
    __tablename__ = "antenna_profiles"

    id: Mapped[int] = mapped_column(primary_key=True)
    slug: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    manufacturer: Mapped[str] = mapped_column(String(160))
    model: Mapped[str] = mapped_column(String(160))
    antenna_type: Mapped[str] = mapped_column(String(80))
    mimo_port_count: Mapped[int] = mapped_column(default=2)
    gain_source: Mapped[GainSource] = mapped_column(Enum(GainSource))
    nominal_peak_gain_dbi: Mapped[float | None] = mapped_column(nullable=True)
    gain_by_band_json: Mapped[list] = mapped_column(JSON, default=list)
    cable_type: Mapped[str] = mapped_column(String(120), default="")
    cable_length_m: Mapped[float] = mapped_column(default=0.0)
    estimated_cable_loss_db: Mapped[float | None] = mapped_column(nullable=True)
    connector_loss_db: Mapped[float | None] = mapped_column(nullable=True)
    mounting_location: Mapped[str] = mapped_column(String(160), default="")
    orientation: Mapped[str] = mapped_column(String(160), default="")
    notes: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class TestSite(Base):
    __tablename__ = "test_sites"

    id: Mapped[int] = mapped_column(primary_key=True)
    slug: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(160))
    latitude: Mapped[float | None] = mapped_column(nullable=True)
    longitude: Mapped[float | None] = mapped_column(nullable=True)
    location_description: Mapped[str] = mapped_column(Text, default="")
    indoor_outdoor: Mapped[str] = mapped_column(String(40), default="")
    notes: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class Experiment(Base):
    __tablename__ = "experiments"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(160))
    comparison_dimension: Mapped[ComparisonDimension] = mapped_column(
        Enum(ComparisonDimension),
        default=ComparisonDimension.GENERAL_REPEATABILITY,
    )
    protocol_id: Mapped[int | None] = mapped_column(
        ForeignKey("benchmark_protocols.id"),
        nullable=True,
    )
    site_id: Mapped[int | None] = mapped_column(ForeignKey("test_sites.id"), nullable=True)
    hypothesis: Mapped[str] = mapped_column(Text, default="")
    primary_metrics_json: Mapped[list] = mapped_column(JSON, default=list)
    practical_thresholds_json: Mapped[dict] = mapped_column(JSON, default=dict)
    random_seed: Mapped[int | None] = mapped_column(nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    variants: Mapped[list["ExperimentVariant"]] = relationship(
        back_populates="experiment",
        cascade="all, delete-orphan",
    )


class ExperimentVariant(Base):
    __tablename__ = "experiment_variants"

    id: Mapped[int] = mapped_column(primary_key=True)
    experiment_id: Mapped[int] = mapped_column(ForeignKey("experiments.id"), index=True)
    label: Mapped[str] = mapped_column(String(120))
    expected_routeros_version: Mapped[str | None] = mapped_column(String(80), nullable=True)
    expected_routerboot_version: Mapped[str | None] = mapped_column(String(80), nullable=True)
    expected_modem_snapshot_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    antenna_mapping_json: Mapped[dict] = mapped_column(JSON, default=dict)
    configuration_json: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    experiment: Mapped[Experiment] = relationship(back_populates="variants")


class TestBatch(Base):
    __tablename__ = "test_batches"

    id: Mapped[int] = mapped_column(primary_key=True)
    batch_id: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(160))
    protocol_slug: Mapped[str] = mapped_column(String(80), index=True)
    protocol_hash: Mapped[str] = mapped_column(String(64), index=True)
    router_slug: Mapped[str] = mapped_column(String(80))
    experiment_id: Mapped[int | None] = mapped_column(ForeignKey("experiments.id"), nullable=True)
    variant_id: Mapped[int | None] = mapped_column(
        ForeignKey("experiment_variants.id"),
        nullable=True,
    )
    site_id: Mapped[int | None] = mapped_column(ForeignKey("test_sites.id"), nullable=True)
    antenna_profile_id: Mapped[int | None] = mapped_column(
        ForeignKey("antenna_profiles.id"), nullable=True
    )
    state: Mapped[BatchState] = mapped_column(Enum(BatchState), default=BatchState.DRAFT)
    target_valid_runs: Mapped[int] = mapped_column(default=10)
    max_attempts: Mapped[int] = mapped_column(default=15)
    valid_run_count: Mapped[int] = mapped_column(default=0)
    attempt_count: Mapped[int] = mapped_column(default=0)
    invalid_run_count: Mapped[int] = mapped_column(default=0)
    failed_attempt_count: Mapped[int] = mapped_column(default=0)
    consecutive_failure_count: Mapped[int] = mapped_column(default=0)
    inter_run_cooldown_seconds: Mapped[int] = mapped_column(default=120)
    retry_delay_seconds: Mapped[int] = mapped_column(default=300)
    max_consecutive_failures: Mapped[int] = mapped_column(default=3)
    deadline: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    notes: Mapped[str] = mapped_column(Text, default="")
    state_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    lease_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    attempts: Mapped[list["BatchAttempt"]] = relationship(
        back_populates="batch",
        cascade="all, delete-orphan",
    )


class BatchAttempt(Base):
    __tablename__ = "batch_attempts"

    id: Mapped[int] = mapped_column(primary_key=True)
    batch_pk: Mapped[int] = mapped_column(ForeignKey("test_batches.id"))
    sequence_number: Mapped[int]
    state: Mapped[BatchAttemptState] = mapped_column(
        Enum(BatchAttemptState),
        default=BatchAttemptState.PLANNED,
    )
    run_id: Mapped[str | None] = mapped_column(String(80), nullable=True, index=True)
    planned_start_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    comparison_eligible: Mapped[bool] = mapped_column(default=False)
    outcome_code: Mapped[str | None] = mapped_column(String(80), nullable=True)
    outcome_details_json: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    batch: Mapped[TestBatch] = relationship(back_populates="attempts")


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
    benchmark_protocol_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    protocol_hash: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    result_schema_version: Mapped[int] = mapped_column(default=1)
    experiment_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    variant_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    batch_id: Mapped[str | None] = mapped_column(String(80), nullable=True, index=True)
    batch_attempt_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    comparison_eligible: Mapped[bool] = mapped_column(Boolean, default=False)
    exclusion_reasons_json: Mapped[list] = mapped_column(JSON, default=list)
    environment_snapshot_json: Mapped[dict] = mapped_column(JSON, default=dict)
    environment_snapshot_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    integrity_json: Mapped[dict] = mapped_column(JSON, default=dict)
    application_version: Mapped[str | None] = mapped_column(String(80), nullable=True)
    application_git_commit: Mapped[str | None] = mapped_column(String(80), nullable=True)
    test_node_version: Mapped[str | None] = mapped_column(String(80), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    router: Mapped[RouterProfile] = relationship(back_populates="runs")
    events: Mapped[list["RunEvent"]] = relationship(
        back_populates="run",
        cascade="all, delete-orphan",
    )
    metric_samples: Mapped[list["MetricSample"]] = relationship(
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


class MetricSample(Base):
    __tablename__ = "metric_samples"

    id: Mapped[int] = mapped_column(primary_key=True)
    run_pk: Mapped[int] = mapped_column(ForeignKey("test_runs.id"), index=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    offset_ms: Mapped[int] = mapped_column(Integer, index=True)
    path_id: Mapped[str | None] = mapped_column(String(80), nullable=True, index=True)
    phase: Mapped[str] = mapped_column(String(80), index=True)
    phase_instance: Mapped[str | None] = mapped_column(String(120), nullable=True)
    metric_name: Mapped[str] = mapped_column(String(120), index=True)
    value: Mapped[float] = mapped_column(Float)
    unit: Mapped[str] = mapped_column(String(40))
    validity: Mapped[str] = mapped_column(String(40), default="valid")
    details_json: Mapped[dict] = mapped_column(JSON, default=dict)

    run: Mapped[TestRun] = relationship(back_populates="metric_samples")
