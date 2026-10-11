from __future__ import annotations

from html.parser import HTMLParser
from typing import Any, Callable


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in {"br", "div", "li", "p"}:
            self.parts.append(" ")

    def handle_endtag(self, tag: str) -> None:
        if tag in {"div", "li", "p"}:
            self.parts.append(" ")

    def handle_data(self, data: str) -> None:
        self.parts.append(data)


def _plain_text(value: str) -> str:
    parser = _TextExtractor()
    parser.feed(value)
    parser.close()
    return " ".join("".join(parser.parts).replace("\xa0", " ").split())


def _artist_name(value: Any) -> str | None:
    if not isinstance(value, dict):
        return None
    name = value.get("name")
    if isinstance(name, dict):
        return name.get("display")
    return name


def _date(value: Any) -> str | None:
    if isinstance(value, dict):
        return value.get("original") or value.get("stream") or value.get("download")
    return value


def _audio(item: dict[str, Any]) -> dict[str, Any]:
    info = item.get("audio_info") if isinstance(item.get("audio_info"), dict) else item
    result: dict[str, Any] = {}
    depth = info.get("maximum_bit_depth")
    rate = info.get("maximum_sampling_rate")
    if depth:
        result["bit_depth"] = depth
    if rate:
        result["sample_rate"] = rate
    return result


def compact_album(item: dict[str, Any]) -> dict[str, Any]:
    artist = _artist_name(item.get("artist"))
    artists = item.get("artists")
    if artist is None and isinstance(artists, list) and artists:
        artist = _artist_name(artists[0])
    result: dict[str, Any] = {
        "id": item.get("id"),
        "title": item.get("title"),
        "artist": artist,
    }
    date = item.get("release_date_original") or _date(item.get("dates"))
    if date:
        result["date"] = date
    tracks = item.get("tracks_count")
    if tracks is None:
        tracks = item.get("track_count")
    if tracks is not None:
        result["tracks"] = tracks
    result.update(_audio(item))
    return {key: value for key, value in result.items() if value is not None}


def compact_artist(item: dict[str, Any]) -> dict[str, Any]:
    name = item.get("name")
    if isinstance(name, dict):
        name = name.get("display")
    result = {"id": item.get("id"), "name": name}
    if item.get("albums_count") is not None:
        result["albums"] = item["albums_count"]
    return {key: value for key, value in result.items() if value is not None}


def compact_track(item: dict[str, Any]) -> dict[str, Any]:
    album = item.get("album") if isinstance(item.get("album"), dict) else {}
    artist = item.get("artist")
    if not artist and isinstance(album, dict):
        artist = album.get("artist")
    result: dict[str, Any] = {
        "id": item.get("id"),
        "title": item.get("title"),
        "artist": _artist_name(artist),
        "album_id": album.get("id"),
        "album": album.get("title"),
        "duration": item.get("duration"),
    }
    if item.get("track_number") is not None:
        result["track"] = item["track_number"]
    result.update(_audio(item))
    return {key: value for key, value in result.items() if value is not None}


def compact_playlist(item: dict[str, Any]) -> dict[str, Any]:
    owner = item.get("owner") if isinstance(item.get("owner"), dict) else {}
    title = item.get("name") or item.get("title")
    result = {
        "id": item.get("id"),
        "name": title,
        "owner": owner.get("name") or owner.get("login"),
        "tracks": item.get("tracks_count"),
        "duration": item.get("duration"),
    }
    return {key: value for key, value in result.items() if value is not None}


def compact_label(item: dict[str, Any]) -> dict[str, Any]:
    result = {
        "id": item.get("id"),
        "name": item.get("name"),
        "albums": item.get("albums_count"),
    }
    return {key: value for key, value in result.items() if value is not None}


FORMATTERS: dict[str, Callable[[dict[str, Any]], dict[str, Any]]] = {
    "albums": compact_album,
    "artists": compact_artist,
    "tracks": compact_track,
    "playlists": compact_playlist,
    "labels": compact_label,
}


def compact_collection(payload: dict[str, Any], kind: str) -> dict[str, Any]:
    collection = payload.get(kind, {})
    if not isinstance(collection, dict):
        collection = {}
    items = collection.get("items", [])
    formatter = FORMATTERS[kind]
    return {
        "total": collection.get("total", len(items)),
        "offset": collection.get("offset", 0),
        "items": [formatter(item) for item in items],
    }


def compact_search(payload: dict[str, Any], kind: str) -> dict[str, Any]:
    kinds = ("albums", "artists", "tracks", "playlists") if kind == "all" else (kind,)
    return {name: compact_collection(payload, name) for name in kinds}


def compact_album_suggestions(payload: dict[str, Any]) -> list[dict[str, Any]]:
    albums = payload.get("albums", {})
    items = albums.get("items", []) if isinstance(albums, dict) else []
    return [compact_album(item) for item in items]


def compact_genres(payload: dict[str, Any]) -> list[dict[str, Any]]:
    genres = payload.get("genres", {})
    items = genres.get("items", []) if isinstance(genres, dict) else []
    return [
        {key: item[key] for key in ("id", "name", "slug") if item.get(key) is not None}
        for item in items
    ]


def compact_new_releases(
    payload: dict[str, Any], offset: int, limit: int
) -> dict[str, Any]:
    items = payload.get("items", [])
    return {
        "has_more": bool(payload.get("has_more")),
        "offset": offset,
        "limit": limit,
        "items": [compact_album(item) for item in items],
    }


def compact_album_detail(
    payload: dict[str, Any], *, include_description: bool = True
) -> dict[str, Any]:
    result = compact_album(payload)
    artist = payload.get("artist")
    if isinstance(artist, dict):
        result["artist"] = compact_artist(artist)
    label = payload.get("label")
    if isinstance(label, dict):
        result["label"] = {key: label.get(key) for key in ("id", "name") if label.get(key) is not None}
    genre = payload.get("genre")
    if isinstance(genre, dict) and genre.get("name"):
        result["genre"] = genre["name"]
    if payload.get("duration") is not None:
        result["duration"] = payload["duration"]
    description = payload.get("description")
    if include_description and isinstance(description, str) and description:
        result["description"] = _plain_text(description)
        if payload.get("description_language"):
            result["description_language"] = payload["description_language"]
    tracks = payload.get("tracks", {}).get("items", [])
    result["track_list"] = [compact_track(track) for track in tracks]
    return result


def compact_artist_detail(
    payload: dict[str, Any],
    *,
    include_biography: bool = False,
    top_limit: int = 10,
    release_limit: int = 10,
) -> dict[str, Any]:
    result = compact_artist(payload)
    biography = payload.get("biography")
    if include_biography and isinstance(biography, dict) and biography.get("content"):
        result["biography"] = biography["content"]
    result["top_tracks"] = [
        compact_track(item) for item in payload.get("top_tracks", [])[:top_limit]
    ]
    releases: dict[str, list[dict[str, Any]]] = {}
    included_groups = {"album", "live", "compilation", "epSingle"}
    for group in payload.get("releases", []):
        if not isinstance(group, dict) or not group.get("items"):
            continue
        name = str(group.get("type") or "other")
        if name not in included_groups:
            continue
        releases.setdefault(name, []).extend(
            compact_album(item) for item in group["items"][:release_limit]
        )
    result["releases"] = releases
    return result


def compact_playlist_detail(payload: dict[str, Any]) -> dict[str, Any]:
    result = compact_playlist(payload)
    if payload.get("description"):
        result["description"] = payload["description"]
    tracks = payload.get("tracks", {}).get("items", [])
    result["track_list"] = [compact_track(track) for track in tracks]
    return result
