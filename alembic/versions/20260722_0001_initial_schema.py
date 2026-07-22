"""initial schema

Revision ID: 20260722_0001
Revises:
Create Date: 2026-07-22 07:45:00
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260722_0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "benchmark_protocols",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("slug", sa.String(length=80), nullable=False),
        sa.Column("version", sa.String(length=40), nullable=False),
        sa.Column("name", sa.String(length=160), nullable=False),
        sa.Column("definition_json", sa.JSON(), nullable=False),
        sa.Column("protocol_hash", sa.String(length=64), nullable=False),
        sa.Column("result_schema_version", sa.Integer(), nullable=False),
        sa.Column("status", sa.Enum("DRAFT", "FROZEN", "RETIRED", name="protocolstatus")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("frozen_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_benchmark_protocols_protocol_hash"),
        "benchmark_protocols",
        ["protocol_hash"],
        unique=True,
    )
    op.create_index(
        op.f("ix_benchmark_protocols_slug"), "benchmark_protocols", ["slug"], unique=True
    )

    op.create_table(
        "antenna_profiles",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("slug", sa.String(length=80), nullable=False),
        sa.Column("manufacturer", sa.String(length=160), nullable=False),
        sa.Column("model", sa.String(length=160), nullable=False),
        sa.Column("antenna_type", sa.String(length=80), nullable=False),
        sa.Column("mimo_port_count", sa.Integer(), nullable=False),
        sa.Column(
            "gain_source",
            sa.Enum("MANUFACTURER", "MEASURED", "ESTIMATED", "UNKNOWN", name="gainsource"),
        ),
        sa.Column("nominal_peak_gain_dbi", sa.Float(), nullable=True),
        sa.Column("unknown_gain_reason", sa.Text(), nullable=False),
        sa.Column("gain_by_band_json", sa.JSON(), nullable=False),
        sa.Column("cable_type", sa.String(length=120), nullable=False),
        sa.Column("cable_length_m", sa.Float(), nullable=False),
        sa.Column("estimated_cable_loss_db", sa.Float(), nullable=True),
        sa.Column("connector_loss_db", sa.Float(), nullable=True),
        sa.Column("mounting_location", sa.String(length=160), nullable=False),
        sa.Column("orientation", sa.String(length=160), nullable=False),
        sa.Column("notes", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_antenna_profiles_slug"), "antenna_profiles", ["slug"], unique=True)

    op.create_table(
        "router_profiles",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("slug", sa.String(length=80), nullable=False),
        sa.Column("display_name", sa.String(length=160), nullable=False),
        sa.Column(
            "kind", sa.Enum("MIKROTIK", "GENERIC", "FAKE", name="routerkind"), nullable=False
        ),
        sa.Column("management_host", sa.String(length=255), nullable=True),
        sa.Column("management_protocol", sa.String(length=40), nullable=True),
        sa.Column("username", sa.String(length=120), nullable=True),
        sa.Column("secret_ref", sa.String(length=255), nullable=True),
        sa.Column("expected_gateway", sa.String(length=255), nullable=True),
        sa.Column("controller_interface", sa.String(length=80), nullable=True),
        sa.Column("allow_configuration_changes", sa.Boolean(), nullable=False),
        sa.Column("metadata_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_router_profiles_slug"), "router_profiles", ["slug"], unique=True)

    op.create_table(
        "server_profiles",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("slug", sa.String(length=80), nullable=False),
        sa.Column("display_name", sa.String(length=160), nullable=False),
        sa.Column("control_api_url", sa.String(length=255), nullable=False),
        sa.Column("token_secret_ref", sa.String(length=255), nullable=True),
        sa.Column("public_host", sa.String(length=255), nullable=True),
        sa.Column("metadata_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_server_profiles_slug"), "server_profiles", ["slug"], unique=True)

    op.create_table(
        "test_plans",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("slug", sa.String(length=80), nullable=False),
        sa.Column("name", sa.String(length=160), nullable=False),
        sa.Column("version", sa.String(length=40), nullable=False),
        sa.Column("definition", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_test_plans_slug"), "test_plans", ["slug"], unique=True)

    op.create_table(
        "test_sites",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("slug", sa.String(length=80), nullable=False),
        sa.Column("name", sa.String(length=160), nullable=False),
        sa.Column("latitude", sa.Float(), nullable=True),
        sa.Column("longitude", sa.Float(), nullable=True),
        sa.Column("location_description", sa.Text(), nullable=False),
        sa.Column("indoor_outdoor", sa.String(length=40), nullable=False),
        sa.Column("notes", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_test_sites_slug"), "test_sites", ["slug"], unique=True)

    op.create_table(
        "experiments",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=160), nullable=False),
        sa.Column(
            "comparison_dimension",
            sa.Enum(
                "FIRMWARE",
                "ROUTERBOOT",
                "MODEM_MODEL",
                "MODEM_FIRMWARE",
                "ANTENNA",
                "GENERAL_REPEATABILITY",
                name="comparisondimension",
            ),
            nullable=False,
        ),
        sa.Column("protocol_id", sa.Integer(), nullable=True),
        sa.Column("site_id", sa.Integer(), nullable=True),
        sa.Column("hypothesis", sa.Text(), nullable=False),
        sa.Column("primary_metrics_json", sa.JSON(), nullable=False),
        sa.Column("practical_thresholds_json", sa.JSON(), nullable=False),
        sa.Column("random_seed", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["protocol_id"], ["benchmark_protocols.id"]),
        sa.ForeignKeyConstraint(["site_id"], ["test_sites.id"]),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "experiment_variants",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("experiment_id", sa.Integer(), nullable=False),
        sa.Column("label", sa.String(length=120), nullable=False),
        sa.Column("expected_routeros_version", sa.String(length=80), nullable=True),
        sa.Column("expected_routerboot_version", sa.String(length=80), nullable=True),
        sa.Column("expected_modem_snapshot_hash", sa.String(length=64), nullable=True),
        sa.Column("antenna_mapping_json", sa.JSON(), nullable=False),
        sa.Column("configuration_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["experiment_id"], ["experiments.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_experiment_variants_experiment_id"), "experiment_variants", ["experiment_id"]
    )

    op.create_table(
        "test_batches",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("batch_id", sa.String(length=80), nullable=False),
        sa.Column("name", sa.String(length=160), nullable=False),
        sa.Column("protocol_id", sa.Integer(), nullable=True),
        sa.Column("protocol_slug", sa.String(length=80), nullable=False),
        sa.Column("protocol_hash", sa.String(length=64), nullable=False),
        sa.Column("router_slug", sa.String(length=80), nullable=False),
        sa.Column("experiment_id", sa.Integer(), nullable=True),
        sa.Column("variant_id", sa.Integer(), nullable=True),
        sa.Column("site_id", sa.Integer(), nullable=True),
        sa.Column("antenna_profile_id", sa.Integer(), nullable=True),
        sa.Column(
            "state",
            sa.Enum(
                "DRAFT",
                "SCHEDULED",
                "RUNNING",
                "PAUSE_REQUESTED",
                "PAUSED",
                "CANCEL_REQUESTED",
                "CANCELLED",
                "COMPLETED",
                "FAILED",
                name="batchstate",
            ),
            nullable=False,
        ),
        sa.Column("target_valid_runs", sa.Integer(), nullable=False),
        sa.Column("max_attempts", sa.Integer(), nullable=False),
        sa.Column("valid_run_count", sa.Integer(), nullable=False),
        sa.Column("attempt_count", sa.Integer(), nullable=False),
        sa.Column("invalid_run_count", sa.Integer(), nullable=False),
        sa.Column("failed_attempt_count", sa.Integer(), nullable=False),
        sa.Column("consecutive_failure_count", sa.Integer(), nullable=False),
        sa.Column("inter_run_cooldown_seconds", sa.Integer(), nullable=False),
        sa.Column("retry_delay_seconds", sa.Integer(), nullable=False),
        sa.Column("max_consecutive_failures", sa.Integer(), nullable=False),
        sa.Column("start_after", sa.DateTime(timezone=True), nullable=True),
        sa.Column("deadline", sa.DateTime(timezone=True), nullable=True),
        sa.Column("max_runtime_seconds", sa.Integer(), nullable=True),
        sa.Column("expected_application_version", sa.String(length=80), nullable=True),
        sa.Column("expected_application_git_commit", sa.String(length=80), nullable=True),
        sa.Column("expected_test_node_version", sa.String(length=80), nullable=True),
        sa.Column("expected_protocol_hash", sa.String(length=64), nullable=True),
        sa.Column("expected_variant_snapshot_hash", sa.String(length=64), nullable=True),
        sa.Column("worker_id", sa.String(length=120), nullable=True),
        sa.Column("last_heartbeat_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("notes", sa.Text(), nullable=False),
        sa.Column("state_reason", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["antenna_profile_id"], ["antenna_profiles.id"]),
        sa.ForeignKeyConstraint(["experiment_id"], ["experiments.id"]),
        sa.ForeignKeyConstraint(["protocol_id"], ["benchmark_protocols.id"]),
        sa.ForeignKeyConstraint(["site_id"], ["test_sites.id"]),
        sa.ForeignKeyConstraint(["variant_id"], ["experiment_variants.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_test_batches_batch_id"), "test_batches", ["batch_id"], unique=True)
    op.create_index(op.f("ix_test_batches_protocol_hash"), "test_batches", ["protocol_hash"])
    op.create_index(op.f("ix_test_batches_protocol_slug"), "test_batches", ["protocol_slug"])

    op.create_table(
        "test_runs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("run_id", sa.String(length=80), nullable=False),
        sa.Column("router_id", sa.Integer(), nullable=False),
        sa.Column("plan_slug", sa.String(length=80), nullable=False),
        sa.Column(
            "state",
            sa.Enum(
                "CREATED",
                "QUEUED",
                "PREFLIGHT",
                "AWAITING_CONFIRMATION",
                "PREPARING_ROUTER",
                "VERIFYING_PATHS",
                "WARMING_UP",
                "RUNNING",
                "COOLING_DOWN",
                "ANALYZING",
                "GENERATING_REPORT",
                "RESTORING",
                "COMPLETED",
                "FAILED",
                "CANCEL_REQUESTED",
                "CANCELLED",
                "INTERRUPTED",
                "RECOVERY_REQUIRED",
                name="runstate",
            ),
            nullable=False,
        ),
        sa.Column("state_reason", sa.Text(), nullable=True),
        sa.Column("resolved_plan", sa.JSON(), nullable=False),
        sa.Column("summary", sa.JSON(), nullable=False),
        sa.Column("benchmark_protocol_id", sa.Integer(), nullable=True),
        sa.Column("protocol_hash", sa.String(length=64), nullable=True),
        sa.Column("result_schema_version", sa.Integer(), nullable=False),
        sa.Column("experiment_id", sa.Integer(), nullable=True),
        sa.Column("variant_id", sa.Integer(), nullable=True),
        sa.Column("batch_id", sa.String(length=80), nullable=True),
        sa.Column("batch_attempt_id", sa.Integer(), nullable=True),
        sa.Column("comparison_eligible", sa.Boolean(), nullable=False),
        sa.Column("exclusion_reasons_json", sa.JSON(), nullable=False),
        sa.Column("environment_snapshot_json", sa.JSON(), nullable=False),
        sa.Column("environment_snapshot_hash", sa.String(length=64), nullable=True),
        sa.Column("integrity_json", sa.JSON(), nullable=False),
        sa.Column("application_version", sa.String(length=80), nullable=True),
        sa.Column("application_git_commit", sa.String(length=80), nullable=True),
        sa.Column("test_node_version", sa.String(length=80), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["benchmark_protocol_id"], ["benchmark_protocols.id"]),
        sa.ForeignKeyConstraint(["router_id"], ["router_profiles.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_test_runs_batch_attempt_id"), "test_runs", ["batch_attempt_id"])
    op.create_index(op.f("ix_test_runs_batch_id"), "test_runs", ["batch_id"])
    op.create_index(op.f("ix_test_runs_experiment_id"), "test_runs", ["experiment_id"])
    op.create_index(op.f("ix_test_runs_protocol_hash"), "test_runs", ["protocol_hash"])
    op.create_index(op.f("ix_test_runs_run_id"), "test_runs", ["run_id"], unique=True)
    op.create_index(op.f("ix_test_runs_variant_id"), "test_runs", ["variant_id"])

    op.create_table(
        "batch_attempts",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("batch_pk", sa.Integer(), nullable=False),
        sa.Column("sequence_number", sa.Integer(), nullable=False),
        sa.Column(
            "state",
            sa.Enum(
                "PLANNED",
                "WAITING_FOR_START",
                "CHECKING_PRECONDITIONS",
                "RUNNING",
                "VALID",
                "INVALID",
                "FAILED",
                "SKIPPED",
                "CANCELLED",
                name="batchattemptstate",
            ),
            nullable=False,
        ),
        sa.Column("run_id", sa.String(length=80), nullable=True),
        sa.Column("planned_start_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("comparison_eligible", sa.Boolean(), nullable=False),
        sa.Column("outcome_code", sa.String(length=80), nullable=True),
        sa.Column("outcome_details_json", sa.JSON(), nullable=False),
        sa.Column("environment_snapshot_hash", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["batch_pk"], ["test_batches.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("batch_pk", "sequence_number"),
    )
    op.create_index(op.f("ix_batch_attempts_run_id"), "batch_attempts", ["run_id"])

    op.create_table(
        "metric_samples",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("run_pk", sa.Integer(), nullable=False),
        sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False),
        sa.Column("offset_ms", sa.Integer(), nullable=False),
        sa.Column("path_id", sa.String(length=80), nullable=True),
        sa.Column("phase", sa.String(length=80), nullable=False),
        sa.Column("phase_instance", sa.String(length=120), nullable=True),
        sa.Column("metric_name", sa.String(length=120), nullable=False),
        sa.Column("value", sa.Float(), nullable=False),
        sa.Column("unit", sa.String(length=40), nullable=False),
        sa.Column("validity", sa.String(length=40), nullable=False),
        sa.Column("details_json", sa.JSON(), nullable=False),
        sa.ForeignKeyConstraint(["run_pk"], ["test_runs.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_metric_samples_metric_name"), "metric_samples", ["metric_name"])
    op.create_index(op.f("ix_metric_samples_offset_ms"), "metric_samples", ["offset_ms"])
    op.create_index(op.f("ix_metric_samples_path_id"), "metric_samples", ["path_id"])
    op.create_index(op.f("ix_metric_samples_phase"), "metric_samples", ["phase"])
    op.create_index(op.f("ix_metric_samples_run_pk"), "metric_samples", ["run_pk"])
    op.create_index("ix_metric_samples_run_metric", "metric_samples", ["run_pk", "metric_name"])
    op.create_index("ix_metric_samples_run_offset", "metric_samples", ["run_pk", "offset_ms"])
    op.create_index(
        "ix_metric_samples_run_phase_path", "metric_samples", ["run_pk", "phase", "path_id"]
    )

    op.create_table(
        "run_events",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("run_pk", sa.Integer(), nullable=False),
        sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False),
        sa.Column("event_type", sa.String(length=80), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("details", sa.JSON(), nullable=False),
        sa.ForeignKeyConstraint(["run_pk"], ["test_runs.id"]),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    op.drop_table("run_events")
    op.drop_index("ix_metric_samples_run_phase_path", table_name="metric_samples")
    op.drop_index("ix_metric_samples_run_offset", table_name="metric_samples")
    op.drop_index("ix_metric_samples_run_metric", table_name="metric_samples")
    op.drop_index(op.f("ix_metric_samples_run_pk"), table_name="metric_samples")
    op.drop_index(op.f("ix_metric_samples_phase"), table_name="metric_samples")
    op.drop_index(op.f("ix_metric_samples_path_id"), table_name="metric_samples")
    op.drop_index(op.f("ix_metric_samples_offset_ms"), table_name="metric_samples")
    op.drop_index(op.f("ix_metric_samples_metric_name"), table_name="metric_samples")
    op.drop_table("metric_samples")
    op.drop_index(op.f("ix_batch_attempts_run_id"), table_name="batch_attempts")
    op.drop_table("batch_attempts")
    op.drop_index(op.f("ix_test_runs_variant_id"), table_name="test_runs")
    op.drop_index(op.f("ix_test_runs_run_id"), table_name="test_runs")
    op.drop_index(op.f("ix_test_runs_protocol_hash"), table_name="test_runs")
    op.drop_index(op.f("ix_test_runs_experiment_id"), table_name="test_runs")
    op.drop_index(op.f("ix_test_runs_batch_id"), table_name="test_runs")
    op.drop_index(op.f("ix_test_runs_batch_attempt_id"), table_name="test_runs")
    op.drop_table("test_runs")
    op.drop_index(op.f("ix_test_batches_protocol_slug"), table_name="test_batches")
    op.drop_index(op.f("ix_test_batches_protocol_hash"), table_name="test_batches")
    op.drop_index(op.f("ix_test_batches_batch_id"), table_name="test_batches")
    op.drop_table("test_batches")
    op.drop_index(op.f("ix_experiment_variants_experiment_id"), table_name="experiment_variants")
    op.drop_table("experiment_variants")
    op.drop_table("experiments")
    op.drop_index(op.f("ix_test_sites_slug"), table_name="test_sites")
    op.drop_table("test_sites")
    op.drop_index(op.f("ix_test_plans_slug"), table_name="test_plans")
    op.drop_table("test_plans")
    op.drop_index(op.f("ix_server_profiles_slug"), table_name="server_profiles")
    op.drop_table("server_profiles")
    op.drop_index(op.f("ix_router_profiles_slug"), table_name="router_profiles")
    op.drop_table("router_profiles")
    op.drop_index(op.f("ix_antenna_profiles_slug"), table_name="antenna_profiles")
    op.drop_table("antenna_profiles")
    op.drop_index(op.f("ix_benchmark_protocols_slug"), table_name="benchmark_protocols")
    op.drop_index(op.f("ix_benchmark_protocols_protocol_hash"), table_name="benchmark_protocols")
    op.drop_table("benchmark_protocols")
