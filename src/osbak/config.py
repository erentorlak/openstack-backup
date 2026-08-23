from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, SecretStr


class KeystoneConfig(BaseModel):
    auth_url: str
    project_name: str
    project_domain_name: str = "default"
    user_domain_name: str = "default"
    username: str
    password: SecretStr
    region_name: str = ""


class DatabaseConfig(BaseModel):
    url: str = "sqlite:///osbak.db"


class Settings(BaseModel):
    keystone: KeystoneConfig
    database: DatabaseConfig = DatabaseConfig()
    projects: list[str] = []

    @classmethod
    def from_yaml(cls, path: Path) -> Settings:
        raw: dict[str, Any] = yaml.safe_load(Path(path).read_text()) or {}
        return cls.model_validate(raw)
