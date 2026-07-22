from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from ltap_testbench.cli import _sample_configuration
from ltap_testbench.db.base import Base
from ltap_testbench.db.models import AntennaProfile, BatchState
from ltap_testbench.db.models import TestBatch as DbTestBatch


def test_sample_configuration_is_idempotent_and_creates_draft_batch() -> None:
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine, expire_on_commit=False, future=True)

    with session_factory() as session:
        first = _sample_configuration(session)
        second = _sample_configuration(session)
        batches = session.scalars(select(DbTestBatch)).all()
        antenna = session.scalar(
            select(AntennaProfile).where(AntennaProfile.slug == "generic-2dbi-window")
        )

        assert first["ok"] is True
        assert second["batch_id"] == first["batch_id"]
        assert len(batches) == 1
        assert batches[0].state == BatchState.DRAFT
        assert batches[0].target_valid_runs == 3
        assert batches[0].max_attempts == 5
        assert batches[0].site_id is not None
        assert batches[0].expected_variant_snapshot_hash
        assert antenna is not None
        assert antenna.nominal_peak_gain_dbi == 2.0
        assert antenna.estimated_cable_loss_db is None
        assert first["effective_gain_dbi"] is None
        assert first["effective_gain_unknown_reason"] == "cable_and_or_connector_loss_unknown"
