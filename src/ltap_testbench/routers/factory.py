from ltap_testbench.db.models import RouterKind, RouterProfile
from ltap_testbench.routers.base import RouterAdapter
from ltap_testbench.routers.fake import FakeRouterAdapter
from ltap_testbench.routers.generic import GenericRouterAdapter
from ltap_testbench.routers.mikrotik import MikroTikRouterAdapter


def adapter_for(profile: RouterProfile) -> RouterAdapter:
    if profile.kind == RouterKind.GENERIC:
        return GenericRouterAdapter(profile)
    if profile.kind == RouterKind.FAKE:
        return FakeRouterAdapter(profile)
    if profile.kind == RouterKind.MIKROTIK:
        return MikroTikRouterAdapter(profile)
    raise ValueError(f"Unsupported router kind: {profile.kind}")
