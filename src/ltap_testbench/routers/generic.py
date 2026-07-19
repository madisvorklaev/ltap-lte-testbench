from ltap_testbench.routers.base import RouterAdapter, RouterCheck


class GenericRouterAdapter(RouterAdapter):
    def preflight(self) -> list[RouterCheck]:
        return [
            RouterCheck(
                name="generic-router",
                ok=True,
                message="RouterOS-specific checks skipped for generic/reference router.",
                details={"router_kind": "generic"},
            )
        ]

    def verify_paths(self) -> list[RouterCheck]:
        return [
            RouterCheck(
                name="generic-path",
                ok=True,
                message=(
                    "Generic path verification requires server-observed port/source IP "
                    "in live tests."
                ),
                details={},
            )
        ]
