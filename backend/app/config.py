from functools import lru_cache
from pathlib import Path
from typing import Literal
from zoneinfo import ZoneInfo

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BACKEND_DIR / "data"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=BACKEND_DIR / ".env", env_file_encoding="utf-8", extra="ignore")

    plk_api_key: str = ""
    plk_base_url: str = "https://pdp-api.plk-sa.pl"
    plk_tier: Literal["basic", "standard", "premium"] = "basic"
    carriers: str = "IC"
    poll_interval_s: int | None = None
    mock_mode: bool = False
    plk_naive_tz: str = "Europe/Warsaw"
    cors_origins: str = "http://localhost:5173"
    data_dir: Path = DATA_DIR
    user_agent: str = "ICtracker/0.1 (educational passenger-information project)"
    # Minutes a train is held just before an unreported stop before we assume that stop never reports.
    hold_grace_min: float = 10.0
    # Pause API polling after this many minutes without anyone viewing the map (0 = always poll).
    idle_after_min: float = 5.0

    @field_validator("poll_interval_s", mode="before")
    @classmethod
    def _blank_is_none(cls, v):
        return None if v in ("", None) else v

    @property
    def tz(self) -> ZoneInfo:
        return ZoneInfo(self.plk_naive_tz)

    @property
    def carrier_list(self) -> list[str]:
        return [c.strip() for c in self.carriers.split(",") if c.strip()]

    @property
    def cache_dir(self) -> Path:
        return self.data_dir / "cache"

    @property
    def geo_dir(self) -> Path:
        """Mock stations have fake ids, so their coordinates and segments live apart from the real ones."""
        return self.data_dir / "mock" if self.mock_mode else self.data_dir

    @property
    def stations_geo_path(self) -> Path:
        return self.geo_dir / "stations_geo.json"

    @property
    def overrides_path(self) -> Path:
        return self.data_dir / "overrides" / "station_overrides.csv"

    @property
    def segments_path(self) -> Path:
        return self.geo_dir / "rail_segments.json"

    @property
    def rail_graph_path(self) -> Path:
        return self.data_dir / "rail_graph.pkl"

    @property
    def reports_dir(self) -> Path:
        return self.data_dir / "reports"


@lru_cache
def get_settings() -> Settings:
    return Settings()
