"""add test profiles and campaign snapshots

Revision ID: 20260722_0002
Revises: 20260722_0001
Create Date: 2026-07-22 13:55:00
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260722_0002"
down_revision: str | None = "20260722_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "test_profiles",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("slug", sa.String(length=80), nullable=False),
        sa.Column("name", sa.String(length=160), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("protocol_id", sa.Integer(), nullable=False),
        sa.Column("protocol_hash", sa.String(length=64), nullable=False),
        sa.Column("profile_version", sa.String(length=40), nullable=False),
        sa.Column("is_comparable", sa.Boolean(), nullable=False),
        sa.Column("is_default", sa.Boolean(), nullable=False),
        sa.Column("display_order", sa.Integer(), nullable=False),
        sa.Column("default_target_mode", sa.String(length=40), nullable=False),
        sa.Column("default_target_value", sa.Float(), nullable=False),
        sa.Column("default_inter_run_cooldown_seconds", sa.Integer(), nullable=False),
        sa.Column("default_max_consecutive_failures", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("retired_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["protocol_id"], ["benchmark_protocols.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_test_profiles_slug"), "test_profiles", ["slug"], unique=True)
    op.create_index(op.f("ix_test_profiles_protocol_id"), "test_profiles", ["protocol_id"])
    op.create_index(op.f("ix_test_profiles_protocol_hash"), "test_profiles", ["protocol_hash"])

    columns = {
        "test_profile_id": sa.Column("test_profile_id", sa.Integer(), nullable=True),
        "test_profile_slug": sa.Column("test_profile_slug", sa.String(length=80), nullable=True),
        "test_profile_version": sa.Column(
            "test_profile_version", sa.String(length=40), nullable=True
        ),
        "resolved_profile_snapshot_json": sa.Column(
            "resolved_profile_snapshot_json", sa.JSON(), nullable=True
        ),
        "target_mode": sa.Column("target_mode", sa.String(length=40), nullable=True),
        "requested_target_value": sa.Column("requested_target_value", sa.Float(), nullable=True),
        "requested_target_unit": sa.Column(
            "requested_target_unit", sa.String(length=40), nullable=True
        ),
        "planned_stream_seconds": sa.Column("planned_stream_seconds", sa.Integer(), nullable=True),
        "estimated_minimum_wall_seconds": sa.Column(
            "estimated_minimum_wall_seconds", sa.Integer(), nullable=True
        ),
        "estimated_worst_case_wall_seconds": sa.Column(
            "estimated_worst_case_wall_seconds", sa.Integer(), nullable=True
        ),
    }
    for column in columns.values():
        op.add_column("test_batches", column)
    op.create_index(
        op.f("ix_test_batches_test_profile_slug"),
        "test_batches",
        ["test_profile_slug"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_test_batches_test_profile_slug"), table_name="test_batches")
    for name in (
        "estimated_worst_case_wall_seconds",
        "estimated_minimum_wall_seconds",
        "planned_stream_seconds",
        "requested_target_unit",
        "requested_target_value",
        "target_mode",
        "resolved_profile_snapshot_json",
        "test_profile_version",
        "test_profile_slug",
        "test_profile_id",
    ):
        op.drop_column("test_batches", name)
    op.drop_index(op.f("ix_test_profiles_protocol_hash"), table_name="test_profiles")
    op.drop_index(op.f("ix_test_profiles_protocol_id"), table_name="test_profiles")
    op.drop_index(op.f("ix_test_profiles_slug"), table_name="test_profiles")
    op.drop_table("test_profiles")
