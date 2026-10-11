"""Command-line interface."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .auth import (
    default_cookies_path,
    environment_state,
    export_state,
    import_browser_state,
    import_cookies,
    interactive_login,
    load_config,
    save_config,
)
from .client import BandcampClient, BandcampError, WishlistPage


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="bandcamp",
        description="Read public Bandcamp wishlists as JSON; no private-wishlist support.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""Workflow:
  auth status                         configured identity/cookie metadata, not validity
  wishlist list                       read the configured fan's public wishlist
  wishlist list --username NAME        select another fan (or use --fan-id ID)
  wishlist list --cursor CURSOR        fetch the next page using next_cursor
  wishlist list --all --pretty         fetch all pages as readable JSON
Results are {items,next_cursor}; the first page has up to 10 items, later pages
up to 20. Wishlists are public: successful reads alone do not prove cookies valid.
See SUBCOMMAND --help for options. JSON goes to stdout; errors go to stderr/exit 1.

Authentication:
  For Amp orbs, use the personal secret BANDCAMP_STATE_JSON. Its JSON object has
  cookies (required Playwright-shaped list, possibly empty), optional nonempty
  username and positive integer fan_id; no other top-level keys.
  Cookie name/value/domain/path are strings; secure/httpOnly optional booleans,
  expires an optional finite number (-1 or 0 for session). Only Bandcamp domains
  are used. This exclusively replaces local config/cookies, including --cookies
  and BANDCAMP_COOKIES. Invalid bundles fail without fallback; environment-mode
  reads do not write credentials or resolved identity, and auth login is disabled.
  auth export-state FILE writes a NEW private 0600 identity-cookie-only bundle.
  Never print, log or commit its contents. Credentials can expire; refresh locally.
  Without the JSON env variable, use auth login --from-cookies FILE or --from-state
  FILE (optional --username NAME). Local files live in ~/.config/bandcamp or under
  XDG_CONFIG_HOME; BANDCAMP_CONFIG_DIR and BANDCAMP_COOKIES override these paths.
""",
    )
    parser.add_argument("--version", action="version", version="%(prog)s 0.1.0")
    commands = parser.add_subparsers(dest="command", required=True)

    wishlist = commands.add_parser("wishlist", help="work with your wishlist")
    wishlist_commands = wishlist.add_subparsers(dest="wishlist_command", required=True)
    list_parser = wishlist_commands.add_parser("list", help="list wishlist items as JSON")
    list_parser.add_argument("--username", help="Bandcamp fan username")
    list_parser.add_argument("--fan-id", type=int, help="Bandcamp fan ID")
    list_parser.add_argument("--cursor", help="next_cursor from the previous result")
    list_parser.add_argument("--all", action="store_true", help="fetch every page")
    list_parser.add_argument("--pretty", action="store_true", help="pretty-print JSON")
    list_parser.add_argument("--cookies", type=Path, help="Netscape cookies.txt file")

    auth = commands.add_parser("auth", help="manage Bandcamp login cookies")
    auth_commands = auth.add_subparsers(dest="auth_command", required=True)
    login = auth_commands.add_parser("login", help="save Bandcamp login cookies")
    sources = login.add_mutually_exclusive_group()
    sources.add_argument(
        "--from-cookies", type=Path, metavar="FILE",
        help="import a Netscape cookies.txt file",
    )
    sources.add_argument(
        "--from-state", type=Path, metavar="FILE",
        help="import an agent-browser/Playwright state JSON file",
    )
    login.add_argument("--username", help="save your Bandcamp fan username")
    auth_commands.add_parser("status", help="show active authentication metadata, never cookies")
    export = auth_commands.add_parser("export-state", help="export identity-only auth to a new 0600 file")
    export.add_argument("file", type=Path, help="new secret JSON file (existing files refused)")

    return parser


def _cookies_from_args(path: Path | None) -> Path | None:
    if environment_state() is not None:
        return None
    if path:
        path = path.expanduser()
        if not path.exists():
            raise BandcampError(f"cookies file does not exist: {path}")
        return path
    default = default_cookies_path()
    return default if default.exists() else None


def wishlist_list(args: argparse.Namespace) -> int:
    config = load_config()
    username = args.username or config.get("username")
    configured_fan_id = config.get("fan_id")
    if args.username and args.username != config.get("username"):
        configured_fan_id = None
    fan_id = args.fan_id or configured_fan_id
    if not args.cursor and not fan_id and not username:
        raise BandcampError(
            "a fan ID or username is required; use --fan-id or --username"
        )

    client = BandcampClient(_cookies_from_args(args.cookies))
    if args.cursor:
        page = client.next_wishlist_page(args.cursor)
    else:
        if not fan_id:
            fan_id = client.resolve_fan_id(username)
            config.update({"username": username, "fan_id": fan_id})
            save_config(config)
        page = client.first_wishlist_page(int(fan_id))

    if args.all:
        items = list(page.items)
        seen_cursors: set[str] = set()
        while page.next_token:
            cursor = page.as_json()["next_cursor"]
            if cursor in seen_cursors or len(seen_cursors) >= 5000:
                raise BandcampError("wishlist pagination did not terminate")
            seen_cursors.add(cursor)
            page = client.next_wishlist_page(cursor)
            items.extend(page.items)
        page = WishlistPage(items, page.fan_id, None)

    indent = 2 if args.pretty else None
    separators = None if args.pretty else (",", ":")
    print(json.dumps(page.as_json(), indent=indent, separators=separators, ensure_ascii=False))
    return 0


def auth_login(args: argparse.Namespace) -> int:
    if environment_state() is not None:
        raise BandcampError("auth login is disabled while BANDCAMP_STATE_JSON is set")
    destination = default_cookies_path()
    if args.from_cookies:
        import_cookies(args.from_cookies.expanduser(), destination)
        count_message = "Imported Bandcamp cookies"
    elif args.from_state:
        count = import_browser_state(args.from_state.expanduser(), destination)
        count_message = f"Imported {count} Bandcamp cookie(s)"
    else:
        count = interactive_login(destination)
        count_message = f"Saved {count} Bandcamp cookie(s)"

    config = load_config()
    if args.username:
        username = args.username.strip().strip("/")
        client = BandcampClient(destination)
        config.update({
            "username": username,
            "fan_id": client.resolve_fan_id(username),
        })
        save_config(config)
    print(f"{count_message} to {destination}", file=sys.stderr)
    if not args.username and not config.get("username"):
        print(
            "Set your fan username with: bandcamp auth login --username NAME "
            "--from-cookies FILE",
            file=sys.stderr,
        )
    return 0


def auth_status() -> int:
    config = load_config()
    state = environment_state()
    if state is not None:
        print(json.dumps({**config, "source": "environment",
                          "cookies_present": bool(list(BandcampClient().cookie_jar))},
                         separators=(",", ":")))
        return 0
    cookies = default_cookies_path()
    value = {
        "username": config.get("username"),
        "fan_id": config.get("fan_id"),
        "cookies_file": str(cookies),
        "cookies_present": cookies.exists(),
    }
    print(json.dumps(value, separators=(",", ":")))
    return 0


def run(args: argparse.Namespace) -> int:
    if args.command == "wishlist" and args.wishlist_command == "list":
        return wishlist_list(args)
    if args.command == "auth" and args.auth_command == "login":
        return auth_login(args)
    if args.command == "auth" and args.auth_command == "status":
        return auth_status()
    if args.command == "auth" and args.auth_command == "export-state":
        config = load_config()
        client = BandcampClient(_cookies_from_args(None))
        try:
            export_state(args.file.expanduser(), config, client.cookie_jar)
        except OSError:
            raise BandcampError("could not create private export file (use a new writable path)") from None
        return 0
    raise AssertionError("unreachable")


def main(argv: list[str] | None = None) -> int:
    try:
        return run(build_parser().parse_args(argv))
    except BandcampError as exc:
        print(f"bandcamp: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\nbandcamp: interrupted", file=sys.stderr)
        return 130
    except BrokenPipeError:
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
