import json

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

import ltap_testbench.cli as cli
from ltap_testbench.cli import _sample_configuration, _stable_hash, _stable_modem_snapshot
from ltap_testbench.db.base import Base
from ltap_testbench.db.models import (
    AntennaProfile,
    BatchState,
    ExperimentVariant,
    GainSource,
    RouterKind,
    RouterProfile,
)
from ltap_testbench.db.models import TestBatch as DbTestBatch
from ltap_testbench.routers.base import RouterCheck


def _session_factory():
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False, future=True)


def test_sample_configuration_is_idempotent_and_creates_draft_batch() -> None:
    session_factory = _session_factory()

    with session_factory() as session:
        first = _sample_configuration(session)
        second = _sample_configuration(session)
        batches = session.scalars(select(DbTestBatch)).all()
        antenna = session.scalar(
            select(AntennaProfile).where(AntennaProfile.slug == "generic-2db-window-2m")
        )

        assert first["configuration_created"] is True
        assert first["ready_to_start"] is False
        assert "test_node_unavailable" in first["blocking_errors"]
        assert second["batch"]["batch_id"] == first["batch"]["batch_id"]
        assert len(batches) == 1
        assert batches[0].state == BatchState.DRAFT
        assert batches[0].target_valid_runs == 3
        assert batches[0].max_attempts == 5
        assert batches[0].site_id is not None
        assert batches[0].antenna_profile_id == antenna.id
        assert batches[0].expected_variant_snapshot_hash
        assert antenna is not None
        assert antenna.gain_source == GainSource.ESTIMATED
        assert antenna.nominal_peak_gain_dbi == 2.0
        assert antenna.cable_type == "unknown"
        assert antenna.cable_length_m == 2.0
        assert antenna.estimated_cable_loss_db is None
        assert antenna.connector_loss_db is None
        assert antenna.mounting_location == "vehicle window"
        assert first["antenna_profile"]["effective_gain_dbi"] is None
        assert (
            first["antenna_profile"]["effective_gain_unknown_reason"]
            == "cable_and_or_connector_loss_unknown"
        )
        assert "physical antenna mapping assumed" in first["warnings"]


def test_stable_modem_snapshot_hash_ignores_radio_but_tracks_identity() -> None:
    paths = [{"id": "lte1", "interface": "lte1", "slot": "slot-a"}]
    base = [
        {
            "path_id": "lte1",
            "lte": {"imei_hash": "imei-hash"},
            "monitor": {"model": "RM500", "revision": "1.0", "rsrp": "-80", "cell-id": "1"},
        }
    ]
    radio_changed = [
        {
            "path_id": "lte1",
            "lte": {"imei_hash": "imei-hash"},
            "monitor": {"model": "RM500", "revision": "1.0", "rsrp": "-95", "cell-id": "9"},
        }
    ]
    modem_changed = [
        {
            "path_id": "lte1",
            "lte": {"imei_hash": "imei-hash"},
            "monitor": {"model": "RM500", "revision": "2.0", "rsrp": "-80", "cell-id": "1"},
        }
    ]

    assert _stable_hash(_stable_modem_snapshot(base, paths)) == _stable_hash(
        _stable_modem_snapshot(radio_changed, paths)
    )
    assert _stable_hash(_stable_modem_snapshot(base, paths)) != _stable_hash(
        _stable_modem_snapshot(modem_changed, paths)
    )


class _FakeAdapter:
    def __init__(self, model: str):
        self.model = model

    def collect_environment_snapshot(self) -> dict:
        return {
            "router": {
                "identity": {"name": "ltap-live"},
                "resource": {"version": "7.16", "board-name": "LtAP"},
                "routerboard": {
                    "model": "LtAP LTE6",
                    "current-firmware": "7.16",
                    "upgrade-firmware": "7.16",
                },
                "packages": [{"name": "routeros", "version": "7.16"}],
            },
            "paths": [
                {
                    "path_id": "lte1",
                    "interface": "lte1",
                    "lte": {"imei_hash": "hashed-imei-1"},
                    "monitor": {"model": self.model, "revision": "1.0"},
                },
                {
                    "path_id": "lte2",
                    "interface": "lte2",
                    "lte": {"imei_hash": "hashed-imei-2"},
                    "monitor": {"model": self.model, "revision": "1.0"},
                },
            ],
        }

    def verify_paths(self) -> list[RouterCheck]:
        return [
            RouterCheck(
                "path-lte1",
                True,
                "lte1 is registered; route table check passed.",
                {},
            ),
            RouterCheck(
                "path-lte2",
                True,
                "lte2 is registered; route table check passed.",
                {},
            ),
        ]


def test_sample_configuration_versions_variant_when_hardware_changes(monkeypatch) -> None:
    session_factory = _session_factory()
    state = {"model": "RM500"}

    def fake_adapter(_router):
        return _FakeAdapter(state["model"])

    monkeypatch.setattr(cli, "adapter_for", fake_adapter)
    monkeypatch.setattr(
        cli,
        "_server_health",
        lambda _server: (
            {
                "ok": True,
                "version": "stockbot-test",
                "measurement_implementation_version": "stockbot-measurement-test",
            },
            [],
        ),
    )

    with session_factory() as session:
        session.add(
            RouterProfile(
                slug="r1-ltap-live",
                display_name="R1 LtAP live",
                kind=RouterKind.MIKROTIK,
                management_host="192.168.101.254",
                management_protocol="routeros-api",
                username="admin",
                secret_ref="env:LTAP_R1_PASSWORD",
                metadata_json={
                    "paths": [
                        {
                            "id": "lte1",
                            "interface": "lte1",
                            "routing_table": "to-lte1",
                            "ports": {"start": 18080, "end": 18080},
                        },
                        {
                            "id": "lte2",
                            "interface": "lte2",
                            "routing_table": "to-lte2",
                            "ports": {"start": 18081, "end": 18081},
                        },
                    ]
                },
            )
        )
        session.commit()

        first = _sample_configuration(session)
        state["model"] = "RM502"
        second = _sample_configuration(session)
        variants = session.scalars(select(ExperimentVariant)).all()
        database_dump = json.dumps(
            {
                "variants": [variant.configuration_json for variant in variants],
                "first": first,
                "second": second,
            },
            default=str,
        )

        assert first["ready_to_start"] is True
        assert second["ready_to_start"] is True
        assert len(variants) == 2
        assert variants[0].expected_modem_snapshot_hash != variants[1].expected_modem_snapshot_hash
        assert "Current connected-router baseline v2" in {variant.label for variant in variants}
        assert "hashed-imei-1" in database_dump
        assert "123456789012345" not in database_dump
