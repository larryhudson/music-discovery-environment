from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any


class ConfigError(RuntimeError):
    pass


def _reject_json_constant(value: str) -> Any:
    raise ValueError("Non-standard JSON constant")


def default_config_path() -> Path:
    override = os.environ.get("QOBUZ_CONFIG")
    if override:
        return Path(override).expanduser()
    xdg = os.environ.get("XDG_CONFIG_HOME")
    root = Path(xdg).expanduser() if xdg else Path.home() / ".config"
    return root / "qobuz-cli" / "config.json"


@dataclass(frozen=True)
class Config:
    app_id: str
    user_auth_token: str

    @classmethod
    def load(cls, path: Path | None = None) -> "Config":
        if "QOBUZ_STATE_JSON" in os.environ:
            try:
                state = json.loads(
                    os.environ["QOBUZ_STATE_JSON"], parse_constant=_reject_json_constant
                )
            except (ValueError, RecursionError):
                raise ConfigError("Invalid QOBUZ_STATE_JSON authentication bundle") from None
            if not isinstance(state, dict) or any(
                not isinstance(state.get(field), str) or not state[field].strip()
                for field in ("app_id", "user_auth_token")
            ):
                raise ConfigError("Invalid QOBUZ_STATE_JSON authentication bundle") from None
            return cls(state["app_id"], state["user_auth_token"])

        path = path or default_config_path()
        data: dict[str, Any] = {}
        if path.exists():
            try:
                data = json.loads(path.read_text())
            except (OSError, json.JSONDecodeError) as exc:
                raise ConfigError(f"Cannot read config at {path}: {exc}") from exc

        app_id = os.environ.get("QOBUZ_APP_ID") or data.get("app_id")
        token = os.environ.get("QOBUZ_USER_AUTH_TOKEN") or data.get("user_auth_token")
        if not app_id or not token:
            raise ConfigError(
                "Qobuz authentication is missing. Run: qobuz auth import-har PATH"
            )
        return cls(str(app_id), str(token))

    @staticmethod
    def auth_source() -> str:
        """Describe the active source after a successful load, without secrets."""
        if "QOBUZ_STATE_JSON" in os.environ:
            return "QOBUZ_STATE_JSON"
        supplied = [
            name for name in ("QOBUZ_APP_ID", "QOBUZ_USER_AUTH_TOKEN")
            if os.environ.get(name)
        ]
        if len(supplied) < 2:
            supplied.append("config")
        return " + ".join(supplied)


def _header_map(entry: dict[str, Any]) -> dict[str, str]:
    headers = entry.get("request", {}).get("headers", [])
    return {
        str(item.get("name", "")).lower(): str(item.get("value", ""))
        for item in headers
    }


def credentials_from_har(path: Path) -> Config:
    try:
        data = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        raise ConfigError(f"Cannot read HAR at {path}: {exc}") from exc

    found: Config | None = None
    entries = data.get("log", {}).get("entries", [])
    for entry in entries:
        url = str(entry.get("request", {}).get("url", ""))
        if "www.qobuz.com/api.json/0.2/" not in url:
            continue
        headers = _header_map(entry)
        app_id = headers.get("x-app-id")
        token = headers.get("x-user-auth-token")
        if app_id and token:
            found = Config(app_id, token)

    if found is None:
        raise ConfigError(
            "No Qobuz API credentials found in the HAR. Record an authenticated API request first."
        )
    return found


def save_config(config: Config, path: Path | None = None) -> Path:
    path = path or default_config_path()
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    try:
        path.parent.chmod(0o700)
    except OSError:
        pass

    payload = json.dumps(
        {"app_id": config.app_id, "user_auth_token": config.user_auth_token},
        separators=(",", ":"),
    )
    fd, temporary = tempfile.mkstemp(prefix=".config-", dir=path.parent, text=True)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w") as handle:
            handle.write(payload)
            handle.write("\n")
        os.replace(temporary, path)
        path.chmod(0o600)
    except Exception:
        try:
            os.close(fd)
        except OSError:
            pass
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise
    return path
