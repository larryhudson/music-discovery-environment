"""Small client for Bandcamp's undocumented wishlist endpoints."""

from __future__ import annotations

import base64
import http.cookiejar
import json
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any

MOBILE_UA = "Bandcamp/11.8.4 (Android 14; Pixel 8)"
FAN_SEARCH_API = "https://bandcamp.com/api/fuzzysearch/2/app_autocomplete"
MOBILE_WISHLIST_API = "https://bandcamp.com/api/mobile/26/fan_wishlist"
WISHLIST_API = "https://bandcamp.com/api/fancollection/1/wishlist_items"
MOBILE_PAGE_SIZE = 10
DEFAULT_PAGE_SIZE = 20


class BandcampError(RuntimeError):
    """An expected Bandcamp or input error."""


def encode_cursor(fan_id: int, token: str) -> str:
    raw = json.dumps({"f": fan_id, "t": token}, separators=(",", ":")).encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def decode_cursor(cursor: str) -> tuple[int, str]:
    try:
        padding = "=" * (-len(cursor) % 4)
        value = json.loads(base64.urlsafe_b64decode(cursor + padding))
        fan_id = int(value["f"])
        token = value["t"]
        if not token or not isinstance(token, str):
            raise ValueError
        return fan_id, token
    except (ValueError, TypeError, KeyError, json.JSONDecodeError) as exc:
        raise BandcampError("invalid wishlist cursor") from exc


def normalize_mobile_token(token: str | None) -> str | None:
    """Convert a mobile item token into fancollection's exclusive cursor."""
    if not token:
        return None
    parts = token.split(":")
    if (len(parts) == 5 and parts[1] == "-" and len(parts[2]) > 1
            and parts[2][0] in "atp" and parts[2][1:].isdigit()):
        return f"{parts[0]}:{parts[2][1:]}:{parts[2][0]}::"
    return token


def compact_item(item: dict[str, Any]) -> dict[str, Any]:
    """Return the stable, useful subset of Bandcamp's large item object."""
    item_type = item.get("tralbum_type") or item.get("item_type")
    if item_type in ("a", "album"):
        item_type = "album"
    elif item_type in ("t", "track"):
        item_type = "track"

    result = {
        "id": item.get("tralbum_id") or item.get("item_id"),
        "type": item_type,
        "artist": item.get("band_name") or item.get("artist"),
        "title": item.get("item_title") or item.get("title"),
        "url": item.get("item_url") or item.get("url"),
        "image_url": item.get("item_art_url"),
    }
    return {key: value for key, value in result.items() if value is not None}


@dataclass
class WishlistPage:
    items: list[dict[str, Any]]
    fan_id: int
    next_token: str | None

    def as_json(self) -> dict[str, Any]:
        return {
            "items": [compact_item(item) for item in self.items],
            "next_cursor": (
                encode_cursor(self.fan_id, self.next_token)
                if self.next_token
                else None
            ),
        }


class BandcampClient:
    def __init__(self, cookies_file: Path | None = None, timeout: float = 30) -> None:
        from .auth import environment_state, state_cookie_jar

        self.timeout = timeout
        state = environment_state()
        jar = state_cookie_jar(state) if state is not None else http.cookiejar.MozillaCookieJar()
        if state is None and cookies_file:
            try:
                # Browser-state exports represent session cookies with expiry 0.
                jar.load(str(cookies_file), ignore_discard=True, ignore_expires=True)
            except (OSError, http.cookiejar.LoadError) as exc:
                raise BandcampError(f"could not load cookies from {cookies_file}: {exc}") from exc
        self.cookie_jar = jar
        self.opener = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(jar)
        )

    def _request(self, request: urllib.request.Request) -> bytes:
        for attempt in range(3):
            try:
                with self.opener.open(request, timeout=self.timeout) as response:
                    return response.read()
            except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError) as exc:
                if attempt == 2:
                    raise BandcampError(f"Bandcamp request failed: {exc}") from exc
                time.sleep(2**attempt)
        raise AssertionError("unreachable")

    @staticmethod
    def _validate_payload(data: Any) -> dict[str, Any]:
        if not isinstance(data, dict):
            raise BandcampError("Bandcamp returned invalid JSON")
        if data.get("error"):
            raise BandcampError(str(data.get("error_message") or "Bandcamp API error"))
        return data

    def _get_json(self, url: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        if params:
            url += "?" + urllib.parse.urlencode(params)
        request = urllib.request.Request(
            url, headers={"Accept": "application/json", "User-Agent": MOBILE_UA}
        )
        try:
            data = json.loads(self._request(request))
        except json.JSONDecodeError as exc:
            raise BandcampError("Bandcamp returned invalid JSON") from exc
        return self._validate_payload(data)

    def _post(self, url: str, payload: dict[str, Any]) -> dict[str, Any]:
        request = urllib.request.Request(
            url,
            data=json.dumps(payload).encode(),
            headers={
                "Accept": "application/json",
                "Content-Type": "application/json",
                "User-Agent": MOBILE_UA,
            },
        )
        try:
            data = json.loads(self._request(request))
        except json.JSONDecodeError as exc:
            raise BandcampError("Bandcamp returned invalid JSON") from exc
        return self._validate_payload(data)

    def resolve_fan_id(self, username: str) -> int:
        username = username.strip().strip("/")
        if not username or "/" in username:
            raise BandcampError("invalid Bandcamp username")
        data = self._get_json(FAN_SEARCH_API, {
            "q": username,
            "param_with_locations": "true",
        })
        for result in data.get("results") or []:
            if (result.get("type") == "f"
                    and str(result.get("username", "")).casefold() == username.casefold()):
                try:
                    return int(result["id"])
                except (KeyError, TypeError, ValueError):
                    break
        raise BandcampError(f"could not resolve Bandcamp fan username {username!r}")

    def first_wishlist_page(self, fan_id: int) -> WishlistPage:
        data = self._get_json(MOBILE_WISHLIST_API, {"fan_id": fan_id})
        items = data.get("items") or []
        token = None
        if len(items) >= MOBILE_PAGE_SIZE:
            token = normalize_mobile_token(items[-1].get("token"))
        return WishlistPage(items, fan_id, token)

    def next_wishlist_page(self, cursor: str, count: int = DEFAULT_PAGE_SIZE) -> WishlistPage:
        fan_id, token = decode_cursor(cursor)
        data = self._post(WISHLIST_API, {
            "fan_id": fan_id,
            "older_than_token": token,
            "count": count,
        })
        items = data.get("items") or []
        next_token = data.get("last_token") if data.get("more_available") and items else None
        return WishlistPage(items, fan_id, next_token)
