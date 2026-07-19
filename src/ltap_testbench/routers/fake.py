from ltap_testbench.routers.base import RouterAdapter, RouterCheck


class FakeRouterAdapter(RouterAdapter):
    def preflight(self) -> list[RouterCheck]:
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
                ok=True,
                message="FastTrack simulated disabled for fake runs.",
                details={"enabled": False},
            ),
        ]

    def verify_paths(self) -> list[RouterCheck]:
        return [
            RouterCheck(
                name=f"verify-{path.get('id', 'unknown')}",
                ok=True,
                message="Fake path counters and server observation match.",
                details=path,
            )
            for path in self.profile.metadata_json.get("paths", [])
        ]
