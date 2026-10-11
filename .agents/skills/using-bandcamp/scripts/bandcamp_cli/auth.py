"""Local cookie and identity storage."""

from __future__ import annotations

import json
import http.cookiejar
import math
import os
import shutil
import stat
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from .client import BandcampError

COOKIE_DOMAINS = ("bandcamp.com",)


def environment_state() -> dict[str, Any] | None:
    """Validate the exclusive, in-memory authentication bundle without echoing it."""
    if "BANDCAMP_STATE_JSON" not in os.environ:
        return None
    error = "invalid BANDCAMP_STATE_JSON: expected an object with cookies and optional username/fan_id"
    try:
        state = json.loads(os.environ["BANDCAMP_STATE_JSON"])
        if (not isinstance(state, dict)
                or set(state) - {"username", "fan_id", "cookies"}
                or not isinstance(state.get("cookies"), list)):
            raise ValueError
        if "username" in state and (not isinstance(state["username"], str)
                                    or not state["username"].strip()):
            raise ValueError
        if "fan_id" in state and (type(state["fan_id"]) is not int or state["fan_id"] <= 0):
            raise ValueError
        for cookie in state["cookies"]:
            if not isinstance(cookie, dict):
                raise ValueError
            for field in ("name", "value", "domain", "path"):
                if not isinstance(cookie.get(field), str) or any(
                        char in cookie[field] for char in "\r\n\x00"):
                    raise ValueError
            if (not cookie["name"] or not cookie["domain"]
                    or not cookie["path"].startswith("/")):
                raise ValueError
            for field in ("secure", "httpOnly"):
                if field in cookie and type(cookie[field]) is not bool:
                    raise ValueError
            if "expires" in cookie and (type(cookie["expires"]) not in (int, float)
                                        or not math.isfinite(cookie["expires"])):
                raise ValueError
        return state
    except (ValueError, TypeError, OverflowError):
        raise BandcampError(error) from None


def state_cookie_jar(state: dict[str, Any]) -> http.cookiejar.CookieJar:
    jar = http.cookiejar.CookieJar()
    for cookie in state["cookies"]:
        domain = cookie["domain"]
        if not _is_bandcamp_domain(domain):
            continue
        expires = cookie.get("expires", -1)
        expires = int(expires) if expires > 0 else None
        jar.set_cookie(http.cookiejar.Cookie(
            version=0, name=cookie["name"], value=cookie["value"],
            port=None, port_specified=False, domain=domain,
            domain_specified=domain.startswith("."), domain_initial_dot=domain.startswith("."),
            path=cookie["path"], path_specified=True, secure=cookie.get("secure", False),
            expires=expires, discard=expires is None, comment=None, comment_url=None,
            rest={"HttpOnly": None} if cookie.get("httpOnly") else {}, rfc2109=False,
        ))
    return jar


def export_state(destination: Path, config: dict[str, Any], jar: http.cookiejar.CookieJar) -> None:
    state = {key: config[key] for key in ("username", "fan_id") if key in config}
    state["cookies"] = [
        {"name": cookie.name, "value": cookie.value, "domain": cookie.domain,
         "path": cookie.path, "secure": cookie.secure,
         "httpOnly": (cookie.has_nonstandard_attr("HttpOnly")
                      or cookie.has_nonstandard_attr(http.cookiejar.HTTPONLY_ATTR)),
         "expires": cookie.expires if cookie.expires is not None else -1}
        for cookie in jar
        if cookie.name == "identity" and _is_bandcamp_domain(cookie.domain)
    ]
    destination.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w") as stream:
        stream.write(json.dumps(state, indent=2) + "\n")


def config_dir() -> Path:
    override = os.environ.get("BANDCAMP_CONFIG_DIR")
    if override:
        return Path(override).expanduser()
    root = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    return root / "bandcamp"


def config_path() -> Path:
    return config_dir() / "config.json"


def default_cookies_path() -> Path:
    override = os.environ.get("BANDCAMP_COOKIES")
    return Path(override).expanduser() if override else config_dir() / "cookies.txt"


def load_config() -> dict[str, Any]:
    state = environment_state()
    if state is not None:
        return {key: state[key] for key in ("username", "fan_id") if key in state}
    path = config_path()
    if not path.exists():
        return {}
    try:
        value = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        raise BandcampError(f"could not read {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise BandcampError(f"invalid config file: {path}")
    return value


def save_config(config: dict[str, Any]) -> None:
    if environment_state() is not None:
        return
    path = config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(config, indent=2) + "\n")
    path.chmod(stat.S_IRUSR | stat.S_IWUSR)


def _is_bandcamp_domain(domain: str) -> bool:
    if not isinstance(domain, str):
        return False
    domain = domain.lstrip(".")
    return any(domain == allowed or domain.endswith("." + allowed)
               for allowed in COOKIE_DOMAINS)


def import_browser_state(source: Path, destination: Path) -> int:
    try:
        data = json.loads(source.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        raise BandcampError(f"could not read browser state {source}: {exc}") from exc

    if not isinstance(data, dict) or not isinstance(data.get("cookies"), list):
        raise BandcampError("browser state has no cookies list")
    lines = [
        "# Netscape HTTP Cookie File",
        "# Generated by bandcamp-cli",
    ]
    count = 0
    for cookie in data["cookies"]:
        if not isinstance(cookie, dict):
            continue
        domain = cookie.get("domain", "")
        if not _is_bandcamp_domain(domain):
            continue
        name = cookie.get("name")
        value = cookie.get("value")
        if not isinstance(name, str) or not isinstance(value, str):
            continue
        prefix = "#HttpOnly_" if cookie.get("httpOnly") else ""
        include_subdomains = "TRUE" if domain.startswith(".") else "FALSE"
        secure = "TRUE" if cookie.get("secure") else "FALSE"
        try:
            expires = max(0, int(cookie.get("expires") or 0))
        except (TypeError, ValueError):
            expires = 0
        lines.append(
            f"{prefix}{domain}\t{include_subdomains}\t{cookie.get('path') or '/'}\t"
            f"{secure}\t{expires}\t{name}\t{value}"
        )
        count += 1

    if not count:
        raise BandcampError("browser state contains no Bandcamp cookies")
    _write_private(destination, "\n".join(lines) + "\n")
    return count


def import_cookies(source: Path, destination: Path) -> None:
    try:
        first_line = source.read_text().splitlines()[0]
    except (OSError, IndexError) as exc:
        raise BandcampError(f"could not read cookies file {source}: {exc}") from exc
    if "Netscape HTTP Cookie File" not in first_line:
        raise BandcampError("cookies must be in Netscape cookies.txt format")
    destination.parent.mkdir(parents=True, exist_ok=True)
    if source.resolve() != destination.resolve():
        shutil.copyfile(source, destination)
    destination.chmod(stat.S_IRUSR | stat.S_IWUSR)


def _write_private(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)
    path.chmod(stat.S_IRUSR | stat.S_IWUSR)


def interactive_login(destination: Path) -> int:
    """Use agent-browser for a human-completed login, then save its cookies."""
    if not shutil.which("agent-browser"):
        raise BandcampError(
            "interactive login requires agent-browser; alternatively use "
            "'bandcamp auth login --from-cookies FILE'"
        )

    try:
        subprocess.run(
            ["agent-browser", "open", "https://bandcamp.com/login"],
            check=True,
            stdout=subprocess.DEVNULL,
        )
        print("Complete the Bandcamp login in the browser (including any CAPTCHA).")
        input("Press Enter after login completes: ")
        with tempfile.TemporaryDirectory() as directory:
            state = Path(directory) / "bandcamp-state.json"
            subprocess.run(
                ["agent-browser", "state", "save", str(state)],
                check=True,
                stdout=subprocess.DEVNULL,
            )
            return import_browser_state(state, destination)
    except (OSError, subprocess.CalledProcessError) as exc:
        raise BandcampError(f"interactive login failed: {exc}") from exc
