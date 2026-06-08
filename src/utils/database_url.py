from __future__ import annotations

import os
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit


def get_project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def normalize_database_url(database_url: str | None) -> str:
    raw = (database_url or "").strip()
    if not raw:
        raw = "sqlite+aiosqlite:///./accounting_bot.db"

    if not raw.startswith("sqlite"):
        return raw

    prefix = "sqlite+aiosqlite:///" if raw.startswith("sqlite+aiosqlite:///") else "sqlite:///"
    candidate = raw[len(prefix):]

    db_path = Path(candidate)
    if not db_path.is_absolute():
        db_path = (get_project_root() / db_path).resolve()

    normalized_path = db_path.as_posix()
    if raw.startswith("sqlite+aiosqlite"):
        return f"sqlite+aiosqlite:///{normalized_path}"
    return f"sqlite:///{normalized_path}"


def get_shared_database_url(explicit_url: str | None = None) -> str:
    candidate = (
        explicit_url
        or os.getenv("SHARED_DATABASE_URL")
        or os.getenv("DATABASE_URL")
        or "sqlite+aiosqlite:///./accounting_bot.db"
    )
    return normalize_database_url(candidate)


def get_shared_database_path(explicit_url: str | None = None) -> Path | None:
    database_url = get_shared_database_url(explicit_url)
    if not database_url.startswith("sqlite"):
        return None

    parts = urlsplit(database_url)
    path = parts.path or ""
    if path.startswith("///"):
        path = path[2:]
    return Path(path)
