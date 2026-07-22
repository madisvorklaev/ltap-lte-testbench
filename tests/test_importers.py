from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from ltap_testbench.db.base import Base
from ltap_testbench.db.models import MetricSample
from ltap_testbench.importers.legacy_csv import import_legacy_upload_csv
from ltap_testbench.profiles.defaults import seed_demo_data


def test_import_legacy_upload_csv_marks_runs_ineligible_and_omits_raw_ids(tmp_path) -> None:
    csv_path = tmp_path / "legacy.csv"
    csv_path.write_text(
        "\n".join(
            [
                (
                    "timestamp_utc,run_id,iteration,phase,path_label,url,file_size_bytes,"
                    "upload_time_total_s,upload_speed_mbit_s,upload_size_bytes,interface,status,"
                    "operator,primary_band,imei,imsi,iccid,subscriber_number,rsrp,rsrq,sinr"
                ),
                (
                    "2026-07-16T02:34:21+00:00,abc,1,before,,,,,,,"
                    "lte1,registered,Elisa EE,B20,111,222,333,444,-88,-13.5,4"
                ),
                (
                    "2026-07-16T02:35:21+00:00,abc,1,upload,lte1,http://example,"
                    "1048576,2.0,4.2,1048576,lte1,registered,Elisa EE,B20,"
                    "111,222,333,444,-87,-13.0,5"
                ),
            ]
        )
        + "\n"
    )
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine, expire_on_commit=False, future=True)
    with session_factory() as session:
        seed_demo_data(session)
        imported = import_legacy_upload_csv(
            session,
            csv_path=csv_path,
            router_slug="demo-generic",
        )
        run = imported[0]
        samples = session.scalars(select(MetricSample).where(MetricSample.run_pk == run.id)).all()

        assert run.run_id == "legacy-abc"
        assert run.result_schema_version == 1
        assert run.comparison_eligible is False
        assert run.exclusion_reasons_json == ["legacy_schema_v1", "legacy_sender_side"]
        assert run.summary["upload_results"][0]["speed_upload_mbit_s"] == 4.2
        assert (
            run.environment_snapshot_json["privacy"] == "raw modem identifiers omitted from import"
        )
        assert samples
        assert {sample.metric_name for sample in samples} >= {
            "radio_rsrp",
            "radio_rsrq",
            "radio_sinr",
        }
        for row in run.summary["telemetry_after"]:
            assert "imei" not in row
            assert "imsi" not in row
            assert "iccid" not in row
            assert "subscriber_number" not in row
        assert "imei" not in run.environment_snapshot_json
        assert "imsi" not in run.environment_snapshot_json
        assert "iccid" not in run.environment_snapshot_json
        assert "subscriber_number" not in run.environment_snapshot_json
