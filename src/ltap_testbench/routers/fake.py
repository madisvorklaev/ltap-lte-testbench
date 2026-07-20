from ltap_testbench.routers.base import RouterAdapter, RouterCheck


class FakeRouterAdapter(RouterAdapter):
    def preflight(self) -> list[RouterCheck]:
        scenario = self.profile.metadata_json.get("scenario")
        if scenario == "api-timeout":
            raise TimeoutError("Simulated RouterOS API timeout")
        paths = self.profile.metadata_json.get("paths", [])
        return [
            RouterCheck(
                name="fake-lte-paths",
                ok=bool(paths),
                message=f"Fake adapter has {len(paths)} configured path(s).",
                details={"paths": paths},
            ),
            RouterCheck(
                name="fasttrack",
                ok=scenario != "fasttrack-enabled",
                message=(
                    "FastTrack simulated enabled; benchmark preparation is required."
                    if scenario == "fasttrack-enabled"
                    else "FastTrack simulated disabled for fake runs."
                ),
                details={"enabled": scenario == "fasttrack-enabled"},
            ),
        ]

    def verify_paths(self) -> list[RouterCheck]:
        scenario = self.profile.metadata_json.get("scenario")
        return [
            RouterCheck(
                name=f"verify-{path.get('id', 'unknown')}",
                ok=scenario != "wrong-path",
                message=(
                    "Fake path counters show traffic on the wrong LTE interface."
                    if scenario == "wrong-path"
                    else "Fake path counters and server observation match."
                ),
                details={**path, "scenario": scenario},
            )
            for path in self.profile.metadata_json.get("paths", [])
        ]

    def collect_path_telemetry(self) -> list[dict]:
        return [
            {
                "path_id": path.get("id", "unknown"),
                "interface": path.get("interface") or path.get("id"),
                "status": "registered",
                "operator": "Demo LTE",
                "rsrp": "-82dBm",
                "rsrq": "-9dB",
                "sinr": "18dB",
            }
            for path in self.profile.metadata_json.get("paths", [])
        ]

    def measure_latency(self, target_host: str, count: int = 5) -> list[dict]:
        return [
            {
                "path_id": path.get("id", "unknown"),
                "target_host": target_host,
                "sent": count,
                "received": count,
                "loss_percent": 0.0,
                "avg_ms": 42.0,
                "min_ms": 35.0,
                "max_ms": 63.0,
                "samples_ms": [35.0, 42.0, 63.0][:count],
            }
            for path in self.profile.metadata_json.get("paths", [])
        ]
