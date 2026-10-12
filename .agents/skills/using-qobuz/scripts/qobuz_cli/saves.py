"""Local album-save notes, separate from Qobuz and authentication state."""
from __future__ import annotations

import fcntl
import json
import os
import tempfile
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator


def default_saves_path() -> Path:
    override = os.environ.get("QOBUZ_SAVES_FILE")
    if override:
        return Path(override).expanduser()
    # Resolve from this checkout, not the caller's current working directory.
    return Path(__file__).resolve().parents[5] / "qobuz-saves.json"


def _load(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"version": 1, "saves": []}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (ValueError, OSError) as exc:
        raise ValueError(f"Cannot read saves file {path}: {exc}") from exc
    if not isinstance(data, dict) or data.get("version") != 1 or not isinstance(data.get("saves"), list):
        raise ValueError(f"Invalid saves file schema: {path}")
    ids = set()
    for entry in data["saves"]:
        if not isinstance(entry, dict) or any(
            not isinstance(entry.get(field), str) or not entry[field].strip()
            for field in ("album_id", "album_name", "artist_name", "link", "saved_at", "updated_at")
        ) or (entry.get("reason") is not None and not isinstance(entry["reason"], str)):
            raise ValueError(f"Invalid save record in {path}")
        if entry["album_id"] in ids:
            raise ValueError(f"Duplicate album ID in saves file {path}")
        ids.add(entry["album_id"])
    return data


@contextmanager
def locked_saves(path: Path) -> Iterator[dict[str, Any]]:
    """Serialize read/modify/write, including concurrent CLI processes."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.with_name(path.name + ".lock").open("a", encoding="utf-8") as lock:
        os.chmod(lock.name, 0o600)
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        try:
            yield _load(path)
        finally:
            fcntl.flock(lock.fileno(), fcntl.LOCK_UN)


def record_save(
    path: Path, data: dict[str, Any], album_id: str,
    album_name: str, artist_name: str, reason: str | None,
) -> dict[str, Any]:
    """Upsert one album and atomically replace the JSON. Caller holds the lock."""
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    existing = next((entry for entry in data["saves"] if entry["album_id"] == album_id), None)
    entry = {
        "album_id": album_id,
        "album_name": album_name,
        "artist_name": artist_name,
        "link": f"https://open.qobuz.com/album/{album_id}",
        "reason": reason if reason is not None else (existing.get("reason") if existing else None),
        "saved_at": existing["saved_at"] if existing else now,
        "updated_at": now,
    }
    if existing is None:
        data["saves"].append(entry)
    else:
        existing.update(entry)
    fd, temporary = tempfile.mkstemp(prefix=".qobuz-saves-", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(data, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    return entry
