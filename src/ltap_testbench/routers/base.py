from abc import ABC, abstractmethod
from dataclasses import dataclass

from ltap_testbench.db.models import RouterProfile


@dataclass(frozen=True)
class RouterCheck:
    name: str
    ok: bool
    message: str
    details: dict


class RouterAdapter(ABC):
    def __init__(self, profile: RouterProfile):
        self.profile = profile

    @abstractmethod
    def preflight(self) -> list[RouterCheck]:
        raise NotImplementedError

    @abstractmethod
    def verify_paths(self) -> list[RouterCheck]:
        raise NotImplementedError

    def collect_path_telemetry(self) -> list[dict]:
        return []

    def collect_environment_snapshot(self) -> dict:
        return {
            "router": {
                "slug": self.profile.slug,
                "display_name": self.profile.display_name,
                "kind": self.profile.kind.value,
                "management_host": self.profile.management_host,
            },
            "paths": self.profile.metadata_json.get("paths", [])
            if self.profile.metadata_json
            else [],
        }

    def measure_latency(self, target_host: str, count: int = 5) -> list[dict]:
        return []
