import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from ltap_testbench.benchmarks.defaults import seed_benchmark_protocols
from ltap_testbench.db.base import Base
from ltap_testbench.db.models import BenchmarkProtocol


def test_frozen_benchmark_protocols_are_not_mutated_in_place() -> None:
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine, expire_on_commit=False, future=True)

    with session_factory() as session:
        seed_benchmark_protocols(session)
        protocol = session.scalar(
            select(BenchmarkProtocol).where(BenchmarkProtocol.slug == "comparable-v1")
        )
        assert protocol is not None
        protocol.definition_json = {
            **protocol.definition_json,
            "idle_baseline": {"duration_seconds": 61},
        }
        session.commit()

        with pytest.raises(RuntimeError, match="invalid stored hash"):
            seed_benchmark_protocols(session)
