import time

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from ltap_testbench.db.base import Base
from ltap_testbench.db.models import MetricSample
from ltap_testbench.jobs.engine import create_run
from ltap_testbench.profiles.defaults import seed_demo_data
from ltap_testbench.telemetry.sampler import RunMetricSampler


def test_run_metric_sampler_persists_phase_tagged_latency_and_radio_samples(tmp_path) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'sampler.sqlite3'}", future=True)
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine, expire_on_commit=False, future=True)
    with session_factory() as session:
        seed_demo_data(session)
        run = create_run(session, "demo-fake-ltap", "quick-check")

    sampler = RunMetricSampler(
        session_factory,
        run.run_id,
        target_host="198.51.100.10",
        latency_interval_seconds=0.05,
        radio_interval_seconds=0.05,
    )
    sampler.set_phase("tcp", "round-1")
    sampler.start()
    time.sleep(0.2)
    sampler.stop()

    with session_factory() as session:
        samples = session.scalars(select(MetricSample).order_by(MetricSample.id)).all()

    assert samples
    assert {sample.phase for sample in samples} == {"tcp"}
    assert {sample.phase_instance for sample in samples} == {"round-1"}
    assert "latency_rtt_ms" in {sample.metric_name for sample in samples}
    assert "radio_sample" in {sample.metric_name for sample in samples}
    assert {sample.path_id for sample in samples} >= {"lte1", "lte2"}
