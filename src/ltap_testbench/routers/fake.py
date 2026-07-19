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
