"""Raw archive writer. Preserves original source material before any interpretation
happens, per prd.md's core principle: archive first, interpret second, publish third.
"""

import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path

from app.config import settings


def slugify(value: str | None, default: str = "misc") -> str:
    if not value:
        return default
    value = value.strip().lower()
    value = re.sub(r"[^a-z0-9]+", "_", value)
    return value.strip("_") or default


def sha256_hex(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def archive_dir_for(jurisdiction: str | None, body: str | None, when: datetime) -> Path:
    """Mirrors the archive path convention in prd.md 9.3, e.g.
    /archive/city_of_boston/planning_commission/2026/2026-06-24/
    """
    root = Path(settings.archive_root)
    day = when.strftime("%Y-%m-%d")
    return root / slugify(jurisdiction) / slugify(body) / str(when.year) / day


def write_archive_file(directory: Path, filename: str, content: bytes) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / filename
    # If a file with this name already exists but different content, disambiguate
    # rather than silently overwrite raw evidence.
    if path.exists() and path.read_bytes() != content:
        stem, suffix = path.stem, path.suffix
        content_hash = sha256_hex(content)[:8]
        path = directory / f"{stem}_{content_hash}{suffix}"
    if not path.exists():
        path.write_bytes(content)
    return path


def write_metadata(directory: Path, filename: str, metadata: dict) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / filename
    path.write_text(json.dumps(metadata, indent=2, default=str))
    return path


def now_utc() -> datetime:
    return datetime.now(timezone.utc)
