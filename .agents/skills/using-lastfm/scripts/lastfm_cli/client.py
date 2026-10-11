"""Fetch and privacy-project completed Last.fm scrobbles for an exact UTC window."""

from __future__ import annotations

import os
from datetime import datetime, timezone

UTC = timezone.utc
from pathlib import Path
from typing import Any

import httpx
from dotenv import dotenv_values
from pydantic import BaseModel, ConfigDict, Field, SecretStr, ValidationError, field_validator

LASTFM_ENDPOINT = "https://ws.audioscrobbler.com/2.0/"
DEFAULT_PAGE_SIZE = 200


class LastfmError(RuntimeError):
    """Base error for the Last.fm adapter."""


class LastfmApiError(LastfmError):
    """Last.fm or the network rejected a request."""


class LastfmProtocolError(LastfmError):
    """Last.fm returned a response the adapter could not understand."""


class Scrobble(BaseModel):
    """One completed play in a SQLite-friendly, API-independent shape."""

    model_config = ConfigDict(frozen=True)

    played_at: datetime
    artist_name: str
    track_name: str
    album_name: str | None
    artist_mbid: str | None
    track_mbid: str | None
    album_mbid: str | None
    lastfm_url: str


class _RawNamedValue(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True, populate_by_name=True)

    text: str = Field(alias="#text")
    mbid: str = ""


class _RawDate(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True)

    uts: int


class _RawTrackAttributes(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True)

    nowplaying: str | None = None


class _RawTrack(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True, populate_by_name=True)

    artist: _RawNamedValue
    album: _RawNamedValue
    name: str = Field(min_length=1)
    mbid: str = ""
    url: str = Field(min_length=1)
    played_date: _RawDate | None = Field(default=None, alias="date")
    attributes: _RawTrackAttributes | None = Field(default=None, alias="@attr")


class _RawPageAttributes(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True, populate_by_name=True)

    page: int
    total_pages: int = Field(alias="totalPages", ge=0)


class _RawRecentTracks(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True, populate_by_name=True)

    tracks: tuple[_RawTrack, ...] = Field(default=(), alias="track")
    attributes: _RawPageAttributes = Field(alias="@attr")

    @field_validator("tracks", mode="before")
    @classmethod
    def accept_single_track(cls, value: Any) -> Any:
        # Last.fm occasionally represents a single result as an object instead
        # of a one-element list.
        if isinstance(value, dict):
            return [value]
        return value


class _RawResponse(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True)

    recenttracks: _RawRecentTracks


class LastfmClient:
    """Small client for ``user.getrecenttracks``.

    ``fetch_scrobbles`` accepts a half-open UTC-normalized window ``[start,
    end)``. Inputs must be timezone-aware and aligned to whole seconds because
    Last.fm's API only accepts inclusive Unix-second boundaries.
    """

    def __init__(
        self,
        username: str,
        api_key: str | SecretStr,
        http: httpx.Client,
        *,
        page_size: int = DEFAULT_PAGE_SIZE,
    ) -> None:
        if not username.strip():
            raise ValueError("username must not be empty")
        secret = api_key if isinstance(api_key, SecretStr) else SecretStr(api_key)
        if not secret.get_secret_value():
            raise ValueError("api_key must not be empty")
        if not 1 <= page_size <= DEFAULT_PAGE_SIZE:
            raise ValueError(f"page_size must be between 1 and {DEFAULT_PAGE_SIZE}")

        self._username = username
        self._api_key = secret
        self._http = http
        self._page_size = page_size

    @classmethod
    def from_env(
        cls,
        username: str,
        *,
        env_file: str | Path = ".env",
        timeout_seconds: float = 30.0,
        **kwargs: Any,
    ) -> LastfmClient:
        """Load ``LASTFM_API_KEY`` from the environment or a local env file."""

        api_key = os.environ.get("LASTFM_API_KEY") or dotenv_values(env_file).get("LASTFM_API_KEY")
        if not api_key:
            raise LastfmApiError("LASTFM_API_KEY is not configured")
        return cls(
            username,
            SecretStr(api_key),
            httpx.Client(timeout=timeout_seconds),
            **kwargs,
        )

    def __enter__(self) -> LastfmClient:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def close(self) -> None:
        self._http.close()

    def fetch_scrobbles(self, *, start: datetime, end: datetime) -> tuple[Scrobble, ...]:
        """Fetch all completed scrobbles in the half-open window ``[start, end)``."""

        start_utc = _whole_second_utc(start, "start")
        end_utc = _whole_second_utc(end, "end")
        if end_utc <= start_utc:
            raise ValueError("end must be later than start")

        from_timestamp = int(start_utc.timestamp())
        # Last.fm's `to` parameter is inclusive; our application boundary is not.
        to_timestamp = int(end_utc.timestamp()) - 1
        page_number = 1
        scrobbles: list[Scrobble] = []

        while True:
            body = self._get_page(
                page=page_number,
                from_timestamp=from_timestamp,
                to_timestamp=to_timestamp,
            )
            try:
                page = _RawResponse.model_validate(body).recenttracks
            except ValidationError as error:
                raise LastfmProtocolError(
                    "Last.fm returned an invalid recent-tracks page"
                ) from error

            if page.attributes.page != page_number:
                raise LastfmProtocolError("Last.fm returned an unexpected page number")

            for track in page.tracks:
                if track.attributes and track.attributes.nowplaying == "true":
                    continue
                if track.played_date is None:
                    raise LastfmProtocolError("A completed Last.fm track has no timestamp")

                played_at = datetime.fromtimestamp(track.played_date.uts, tz=UTC)
                if not start_utc <= played_at < end_utc:
                    raise LastfmProtocolError(
                        "Last.fm returned a scrobble outside the requested window"
                    )
                scrobbles.append(_normalize_scrobble(track, played_at))

            if page_number >= page.attributes.total_pages:
                break
            page_number += 1

        return tuple(scrobbles)

    def _get_page(
        self,
        *,
        page: int,
        from_timestamp: int,
        to_timestamp: int,
    ) -> dict[str, Any]:
        try:
            response = self._http.get(
                LASTFM_ENDPOINT,
                params={
                    "method": "user.getrecenttracks",
                    "user": self._username,
                    "api_key": self._api_key.get_secret_value(),
                    "from": from_timestamp,
                    "to": to_timestamp,
                    "limit": self._page_size,
                    "page": page,
                    "format": "json",
                },
            )
            response.raise_for_status()
            body = response.json()
        except httpx.HTTPStatusError as error:
            # Do not chain the request: its URL contains the API key.
            raise LastfmApiError(f"Last.fm returned HTTP {error.response.status_code}") from None
        except httpx.RequestError:
            raise LastfmApiError("Could not reach Last.fm") from None
        except (ValueError, TypeError):
            raise LastfmProtocolError("Last.fm returned a non-JSON response") from None

        if not isinstance(body, dict):
            raise LastfmProtocolError("Last.fm returned a non-object JSON response")
        if "error" in body:
            code = body.get("error")
            message = body.get("message")
            detail = f" ({code}: {message})" if code is not None and message else ""
            raise LastfmApiError(f"Last.fm rejected the recent-tracks request{detail}")
        return body


def _normalize_scrobble(track: _RawTrack, played_at: datetime) -> Scrobble:
    return Scrobble(
        played_at=played_at,
        artist_name=track.artist.text,
        track_name=track.name,
        album_name=track.album.text or None,
        artist_mbid=track.artist.mbid or None,
        track_mbid=track.mbid or None,
        album_mbid=track.album.mbid or None,
        lastfm_url=track.url,
    )


def _whole_second_utc(value: datetime, name: str) -> datetime:
    if value.tzinfo is None:
        raise ValueError(f"{name} must include a timezone")
    if value.microsecond:
        raise ValueError(f"{name} must be aligned to a whole second")
    return value.astimezone(UTC)
