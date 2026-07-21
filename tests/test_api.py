from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from ltap_testbench.api.app import LabRunCreate, _upsert_lab_plan, app
from ltap_testbench.db.base import Base


def test_health() -> None:
    client = TestClient(app)
    response = client.get("/api/v1/health")
    assert response.status_code == 200
    assert response.json()["ok"] is True


def test_router_preflight_api() -> None:
    client = TestClient(app)
    client.post("/api/v1/demo/seed")
    response = client.post("/api/v1/routers/demo-generic/preflight")
    assert response.status_code == 200
    payload = response.json()
    assert "controller" in payload
    assert payload["router"][0]["ok"] is True


def test_lab_plan_keeps_tcp_count_and_udp_pattern() -> None:
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine, expire_on_commit=False, future=True)
    with session_factory() as session:
        plan = _upsert_lab_plan(
            session,
            LabRunCreate(
                tcp_file_size_mb=5,
                tcp_upload_count=3,
                udp_duration_seconds=4,
                udp_bitrate_mbit_s=5,
                udp_pattern="after_each_tcp",
                video_resolution="1080p",
                video_fps=25,
                video_scenario="city",
                antenna="test placement",
            ),
        )

        assert plan.definition["tcp_upload"]["payload_bytes"] == 5 * 1024 * 1024
        assert plan.definition["tcp_upload"]["count"] == 3
        assert plan.definition["udp_upload"]["duration_seconds"] == 4
        assert plan.definition["udp_upload"]["bitrate_mbit_s"] == 5
        assert plan.definition["udp_upload"]["pattern"] == "after_each_tcp"
        assert "tcp-upload" in plan.definition["stages"]
        assert "short-upload" not in plan.definition["stages"]
        assert plan.definition["video_probe"]["resolution"] == "1080p"
        assert "codec" not in plan.definition["video_probe"]
        assert plan.definition["video_probe"]["fps"] == 25
        assert plan.definition["video_probe"]["scenario"] == "city"
        assert plan.definition["metadata"]["lab"]["antenna"] == "test placement"
