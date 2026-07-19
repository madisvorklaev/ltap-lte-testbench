from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="LTAP_TESTBENCH_", env_file=".env")

    data_dir: Path = Path("var")
    database_url: str = "sqlite:///var/ltap-testbench.sqlite3"
    bind_host: str = "127.0.0.1"
    bind_port: int = 8787


@lru_cache
def get_settings() -> Settings:
    return Settings()
