"""运行配置：端口、跨域、运行环境。"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    app_name: str = "光伏电站运维管理平台"
    env: str = "local"
    port: int = 8000
    allowed_origins: list[str] = field(
        default_factory=lambda: [
            "http://127.0.0.1:5173",
            "http://localhost:5173",
        ]
    )
    page_size_default: int = 20
    page_size_max: int = 200
    database_path: Path = field(
        default_factory=lambda: Path(os.getenv("DATABASE_PATH", Path(__file__).resolve().parent.parent / "data" / "ops.db"))
    )

    def __post_init__(self) -> None:
        self.database_path.parent.mkdir(parents=True, exist_ok=True)


settings = Settings()
