from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from . import __version__
from .api import ApiError, QobuzApi
from .config import (
    Config,
    ConfigError,
    credentials_from_har,
    default_config_path,
    save_config,
)
from .formatters import (
    FORMATTERS,
    compact_album_detail,
    compact_album_suggestions,
    compact_artist_detail,
    compact_collection,
    compact_genres,
    compact_new_releases,
    compact_playlist_detail,
    compact_search,
)


TYPE_ALIASES = {
    "release": "album",
    "releases": "album",
    "albums": "album",
    "artists": "artist",
    "tracks": "track",
    "labels": "label",
}


def positive_int(value: str) -> int:
    number = int(value)
    if number < 1:
        raise argparse.ArgumentTypeError("must be at least 1")
    return number


def nonnegative_int(value: str) -> int:
    number = int(value)
    if number < 0:
        raise argparse.ArgumentTypeError("must be at least 0")
    return number


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(
        prog="qobuz",
        description="Token-efficient Qobuz CLI. Compact JSON is the default output.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""Workflow:
  auth status                         read-only credential-validity check
  search QUERY --type albums           discover catalogue IDs
  genres; new-releases --genre Jazz    browse releases and genre filters
  album ID --similar; artist ID --similar; playlist ID
  library all --limit 10               inspect favorites, purchases, playlists
  library albums --source favorites    select favorites/purchases/all
  add album ID; remove album ID        MUTATE favorites immediately, no prompt
Only run add/remove with explicit user authorization; there is no dry-run.
Album/release and library/lib are aliases. Album --no-description omits reviews;
artist --bio includes biography, --top-limit/--release-limit trim details.

Pagination:
  Use --limit N --offset N on search, new-releases, album, playlist, library.
  Increase offset to fetch another page; no automatic paging. Library all applies
  pagination per collection; albums/tracks merge favorites and purchases per page.
  Artist similar results use --similar-limit and --similar-offset.

Global flags must precede the command:
  qobuz --pretty search QUERY; qobuz --raw album ID
  qobuz --config PATH auth status
Compact JSON goes to stdout; JSON errors go to stderr with nonzero exit status.

Authentication (no credential values are printed):
  QOBUZ_STATE_JSON is a JSON object with required non-empty string fields
  app_id and user_auth_token. It overrides --config, QOBUZ_CONFIG and individual
  env vars as a complete in-memory bundle. Invalid JSON/fields fail closed:
  no fallback, network request or config write. Ordinary env-auth commands never
  persist credentials. For Amp orbs, store this bundle as a personal Amp secret
  named QOBUZ_STATE_JSON and expose it to the orb environment.
  auth export-state PATH writes only the active app_id/user_auth_token to a
  private (0600) file for secret setup; never print, commit or share its contents.
  Without QOBUZ_STATE_JSON, QOBUZ_APP_ID and QOBUZ_USER_AUTH_TOKEN override
  respective local fields. Local path: --config PATH, then QOBUZ_CONFIG, then
  $XDG_CONFIG_HOME/qobuz-cli/config.json (default ~/.config/qobuz-cli/config.json).
  auth import-har PATH imports authenticated web-player HAR credentials locally.
  HAR, config and exported state are secrets; do not include them in output.
""",
    )
    root.add_argument("--raw", action="store_true", help="emit the full API response")
    root.add_argument("--pretty", action="store_true", help="indent JSON output")
    root.add_argument("--config", type=Path, help="config file path")
    root.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    commands = root.add_subparsers(dest="command", required=True)

    auth = commands.add_parser("auth", help="manage authentication")
    auth_commands = auth.add_subparsers(dest="auth_command", required=True)
    import_har = auth_commands.add_parser("import-har", help="import API credentials from a HAR")
    import_har.add_argument("path", type=Path)
    auth_commands.add_parser("status", help="check active source and credential validity (read-only)")
    export_state = auth_commands.add_parser(
        "export-state", help="write active credentials to a private JSON file without printing them"
    )
    export_state.add_argument("path", type=Path)

    search = commands.add_parser("search", help="search the Qobuz catalogue")
    search.add_argument("query")
    search.add_argument(
        "--type",
        choices=("all", "albums", "artists", "tracks", "playlists"),
        default="all",
    )
    search.add_argument("--limit", type=positive_int, default=10)
    search.add_argument("--offset", type=nonnegative_int, default=0)

    commands.add_parser("genres", help="list genres accepted by discovery filters")

    new_releases = commands.add_parser(
        "new-releases", aliases=["new"], help="list Qobuz new releases"
    )
    new_releases.add_argument("--limit", type=positive_int, default=50)
    new_releases.add_argument("--offset", type=nonnegative_int, default=0)
    new_releases.add_argument(
        "--genre",
        action="append",
        default=[],
        metavar="NAME_OR_ID",
        help="filter by genre name, slug, or ID; repeat to select multiple genres",
    )

    album = commands.add_parser("album", aliases=["release"], help="get album details and tracks")
    album.add_argument("id")
    album.add_argument("--limit", type=positive_int, default=100)
    album.add_argument("--offset", type=nonnegative_int, default=0)
    album.add_argument(
        "--similar",
        action="store_true",
        help="include recommendations from Qobuz's album suggestion endpoint",
    )
    album.add_argument(
        "--no-description",
        "--no-review",
        dest="include_description",
        action="store_false",
        help="omit the Qobuz editorial description",
    )

    artist = commands.add_parser("artist", help="get artist details")
    artist.add_argument("id")
    artist.add_argument("--sort", default="release_date")
    artist.add_argument("--top-limit", type=positive_int, default=10)
    artist.add_argument("--release-limit", type=positive_int, default=10)
    artist.add_argument("--bio", action="store_true", help="include the full biography")
    artist.add_argument(
        "--similar",
        action="store_true",
        help="include artists from Qobuz's similar-artists endpoint",
    )
    artist.add_argument("--similar-limit", type=positive_int, default=20)
    artist.add_argument("--similar-offset", type=nonnegative_int, default=0)

    playlist = commands.add_parser("playlist", help="get playlist details and tracks")
    playlist.add_argument("id")
    playlist.add_argument("--limit", type=positive_int, default=100)
    playlist.add_argument("--offset", type=nonnegative_int, default=0)

    library = commands.add_parser("library", aliases=["lib"], help="list library items")
    library.add_argument(
        "type",
        nargs="?",
        choices=("all", "albums", "releases", "artists", "tracks", "playlists", "labels"),
        default="albums",
    )
    library.add_argument("--limit", type=positive_int, default=50)
    library.add_argument("--offset", type=nonnegative_int, default=0)
    library.add_argument(
        "--source",
        choices=("all", "favorites", "purchases"),
        default="all",
        help="album/track source (default: merge favorites and purchases)",
    )

    for action in ("add", "remove"):
        change = commands.add_parser(action, help=f"{action} a library favourite")
        change.add_argument(
            "type",
            choices=("album", "release", "artist", "track", "label", "award"),
        )
        change.add_argument("id")

    return root


def emit(value: Any, pretty: bool = False, *, stream: Any = sys.stdout) -> None:
    options = {"ensure_ascii": False}
    if pretty:
        options["indent"] = 2
    else:
        options["separators"] = (",", ":")
    print(json.dumps(value, **options), file=stream)


def _genre_key(value: str) -> str:
    return "".join(character for character in value.casefold() if character.isalnum())


def _resolve_genre_ids(api: QobuzApi, requested: list[str]) -> list[int]:
    if not requested:
        return []
    genres = compact_genres(api.genres())
    lookup: dict[str, int] = {}
    for genre in genres:
        genre_id = int(genre["id"])
        lookup[str(genre_id)] = genre_id
        lookup[_genre_key(str(genre.get("name", "")))] = genre_id
        lookup[_genre_key(str(genre.get("slug", "")))] = genre_id
    result: list[int] = []
    for value in requested:
        genre_id = lookup.get(value) or lookup.get(_genre_key(value))
        if genre_id is None:
            available = ", ".join(str(genre["name"]) for genre in genres)
            raise ValueError(f"Unknown genre '{value}'. Available genres: {available}")
        if genre_id not in result:
            result.append(genre_id)
    return result


def _items(payload: dict[str, Any], kind: str) -> list[dict[str, Any]]:
    collection = payload.get(kind, {})
    return collection.get("items", []) if isinstance(collection, dict) else []


def _library_collection(
    api: QobuzApi,
    kind: str,
    limit: int,
    offset: int,
    source: str,
    raw: bool,
) -> dict[str, Any]:
    if kind == "playlists":
        payload = api.playlists(limit, offset)
        return payload if raw else compact_collection(payload, kind)

    payloads: list[tuple[str, dict[str, Any]]] = []
    if source in ("all", "favorites") or kind not in ("albums", "tracks"):
        payloads.append(("favorite", api.favorites(kind, limit, offset)))
    if source in ("all", "purchases") and kind in ("albums", "tracks"):
        payloads.append(("purchase", api.purchases(kind, limit, offset)))

    if raw:
        return {name: payload for name, payload in payloads}

    formatter = FORMATTERS[kind]
    merged: dict[str, dict[str, Any]] = {}
    order: list[str] = []
    totals: dict[str, int] = {}
    for source_name, payload in payloads:
        collection = payload.get(kind, {})
        totals[source_name] = int(collection.get("total", 0)) if isinstance(collection, dict) else 0
        for item in _items(payload, kind):
            key = str(item.get("id"))
            if key not in merged:
                compact = formatter(item)
                compact["source"] = [source_name]
                merged[key] = compact
                order.append(key)
            elif source_name not in merged[key]["source"]:
                merged[key]["source"].append(source_name)
    return {
        "totals": totals,
        "offset": offset,
        "items": [merged[key] for key in order],
    }


def _run_library(api: QobuzApi, args: argparse.Namespace) -> dict[str, Any]:
    kind = "albums" if args.type == "releases" else args.type
    if kind != "all":
        return _library_collection(api, kind, args.limit, args.offset, args.source, args.raw)
    return {
        item_type: _library_collection(
            api, item_type, args.limit, args.offset, args.source, args.raw
        )
        for item_type in ("albums", "artists", "tracks", "playlists")
    }


def run(args: argparse.Namespace) -> Any:
    config_path = args.config or default_config_path()
    if args.command == "auth":
        if args.auth_command == "import-har":
            config = credentials_from_har(args.path)
            saved = save_config(config, config_path)
            return {"ok": True, "config": str(saved)}
        config = Config.load(config_path)
        if args.auth_command == "export-state":
            saved = save_config(config, args.path)
            return {"ok": True, "path": str(saved)}
        QobuzApi(config).get("favorite/getUserFavoriteIds")
        source = Config.auth_source()
        result = {"authenticated": True, "source": source}
        if "config" in source:
            result["config"] = str(config_path)
        return result

    api = QobuzApi(Config.load(config_path))
    if args.command == "search":
        payload = api.search(args.query, args.limit, args.offset)
        return payload if args.raw else compact_search(payload, args.type)
    if args.command == "genres":
        payload = api.genres()
        return payload if args.raw else {"items": compact_genres(payload)}
    if args.command in ("new-releases", "new"):
        genre_ids = _resolve_genre_ids(api, args.genre)
        payload = api.new_releases(args.limit, args.offset, genre_ids)
        return payload if args.raw else compact_new_releases(
            payload, args.offset, args.limit
        )
    if args.command in ("album", "release"):
        payload = api.album(args.id, args.limit, args.offset)
        suggestions = api.album_suggestions(args.id) if args.similar else None
        if args.raw:
            return {"album": payload, "similar": suggestions} if suggestions else payload
        result = compact_album_detail(
            payload, include_description=args.include_description
        )
        if suggestions is not None:
            result["similar_albums"] = compact_album_suggestions(suggestions)
        return result
    if args.command == "artist":
        payload = api.artist(args.id, args.sort)
        similar = (
            api.similar_artists(args.id, args.similar_limit, args.similar_offset)
            if args.similar
            else None
        )
        if args.raw:
            return {"artist": payload, "similar": similar} if similar else payload
        result = compact_artist_detail(
            payload,
            include_biography=args.bio,
            top_limit=args.top_limit,
            release_limit=args.release_limit,
        )
        if similar is not None:
            result["similar_artists"] = compact_collection(similar, "artists")
        return result
    if args.command == "playlist":
        payload = api.playlist(args.id, args.limit, args.offset)
        return payload if args.raw else compact_playlist_detail(payload)
    if args.command in ("library", "lib"):
        return _run_library(api, args)
    if args.command in ("add", "remove"):
        item_type = TYPE_ALIASES.get(args.type, args.type)
        payload = api.change_favorite(args.command, item_type, args.id)
        if args.raw:
            return payload
        return {
            "ok": bool(payload.get("status")),
            "action": args.command,
            "type": item_type,
            "id": args.id,
        }
    raise AssertionError(f"Unhandled command: {args.command}")


def main(argv: list[str] | None = None) -> None:
    args = parser().parse_args(argv)
    try:
        emit(run(args), args.pretty)
    except (ApiError, ConfigError, OSError, ValueError) as exc:
        emit({"error": str(exc)}, stream=sys.stderr)
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
