from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Mapping

from .config import Config


class ApiError(RuntimeError):
    def __init__(self, message: str, status: int | None = None):
        super().__init__(message)
        self.status = status


class QobuzApi:
    base_url = "https://www.qobuz.com/api.json/0.2"

    def __init__(self, config: Config, timeout: float = 20.0):
        self.config = config
        self.timeout = timeout

    def _request(
        self,
        method: str,
        endpoint: str,
        *,
        query: Mapping[str, Any] | None = None,
        form: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        url = f"{self.base_url}/{endpoint}"
        if query:
            url += "?" + urllib.parse.urlencode(query)
        data = None
        headers = {
            "Accept": "application/json",
            "Referer": "https://play.qobuz.com/",
            "User-Agent": "qobuz-cli/0.1",
            "X-App-Id": self.config.app_id,
            "X-User-Auth-Token": self.config.user_auth_token,
        }
        if form is not None:
            data = urllib.parse.urlencode(form).encode()
            headers["Content-Type"] = "application/x-www-form-urlencoded"

        request = urllib.request.Request(url, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                payload = response.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            payload = exc.read().decode("utf-8", errors="replace")
            message = f"Qobuz API returned HTTP {exc.code}"
            try:
                error = json.loads(payload)
                message = str(error.get("message") or error.get("error") or message)
            except json.JSONDecodeError:
                pass
            raise ApiError(message, exc.code) from None
        except urllib.error.URLError as exc:
            raise ApiError(f"Qobuz API request failed: {exc.reason}") from None

        try:
            result = json.loads(payload)
        except json.JSONDecodeError:
            raise ApiError("Qobuz API returned invalid JSON") from None
        if not isinstance(result, dict):
            raise ApiError("Qobuz API returned an unexpected response")
        code = result.get("code")
        is_error_code = False
        try:
            is_error_code = code is not None and int(code) >= 400
        except (TypeError, ValueError):
            pass
        if result.get("status") == "error" or is_error_code:
            raise ApiError(str(result.get("message") or "Qobuz API error"))
        return result

    def get(self, endpoint: str, **query: Any) -> dict[str, Any]:
        return self._request("GET", endpoint, query=query)

    def post(self, endpoint: str, **form: Any) -> dict[str, Any]:
        return self._request("POST", endpoint, form=form)

    def search(self, query: str, limit: int, offset: int) -> dict[str, Any]:
        return self.get("catalog/search", query=query, limit=limit, offset=offset)

    def genres(self) -> dict[str, Any]:
        return self.get("genre/list")

    def new_releases(
        self, limit: int, offset: int, genre_ids: list[int] | None = None
    ) -> dict[str, Any]:
        query: dict[str, Any] = {"limit": limit, "offset": offset}
        if genre_ids:
            query["genre_ids"] = ",".join(str(value) for value in genre_ids)
        return self._request("GET", "discover/newReleases", query=query)

    def album(self, album_id: str, limit: int, offset: int) -> dict[str, Any]:
        return self.get(
            "album/get",
            album_id=album_id,
            extra="track_ids,albumsFromSameArtist",
            limit=limit,
            offset=offset,
        )

    def album_suggestions(self, album_id: str) -> dict[str, Any]:
        return self.get("album/suggest", album_id=album_id)

    def artist(self, artist_id: str, sort: str = "release_date") -> dict[str, Any]:
        return self.get("artist/page", artist_id=artist_id, sort=sort)

    def similar_artists(
        self, artist_id: str, limit: int, offset: int
    ) -> dict[str, Any]:
        return self.get(
            "artist/getSimilarArtists",
            artist_id=artist_id,
            limit=limit,
            offset=offset,
        )

    def playlist(self, playlist_id: str, limit: int, offset: int) -> dict[str, Any]:
        return self.get(
            "playlist/get",
            playlist_id=playlist_id,
            extra="tracks",
            limit=limit,
            offset=offset,
        )

    def favorites(self, item_type: str, limit: int, offset: int) -> dict[str, Any]:
        return self.get(
            "favorite/getUserFavorites",
            type=item_type,
            limit=limit,
            offset=offset,
        )

    def purchases(self, item_type: str, limit: int, offset: int) -> dict[str, Any]:
        return self.get(
            "purchase/getUserPurchases",
            type=item_type,
            limit=limit,
            offset=offset,
        )

    def playlists(self, limit: int, offset: int) -> dict[str, Any]:
        return self.get("playlist/getUserPlaylists", limit=limit, offset=offset)

    def change_favorite(self, action: str, item_type: str, item_id: str) -> dict[str, Any]:
        fields = {
            "track_ids": "",
            "album_ids": "",
            "artist_ids": "",
            "label_ids": "",
            "award_ids": "",
        }
        field = {
            "track": "track_ids",
            "album": "album_ids",
            "artist": "artist_ids",
            "label": "label_ids",
            "award": "award_ids",
        }[item_type]
        fields[field] = item_id
        endpoint = "favorite/create" if action == "add" else "favorite/delete"
        return self.post(endpoint, **fields)
