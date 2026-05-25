from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


@dataclass(frozen=True)
class AppConfig:
    data_dir: Path
    openai_api_key: str
    openai_model: str
    mealie_planner_base_url: str | None

    @classmethod
    def from_env(cls) -> "AppConfig":
        load_dotenv(".env.local")
        load_dotenv()
        return cls(
            data_dir=Path(os.environ.get("DATA_DIR", "data")),
            openai_api_key=required("OPENAI_API_KEY"),
            openai_model=os.environ.get("OPENAI_MODEL", "gpt-5-mini"),
            mealie_planner_base_url=os.environ.get("MEALIE_PLANNER_BASE_URL") or None,
        )

    @property
    def db_path(self) -> Path:
        return self.data_dir / "instacart_history.sqlite3"


def required(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(f"{name} is required")
    return value
