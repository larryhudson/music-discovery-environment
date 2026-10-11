"""Read-only, JSON command-line interface for completed Last.fm plays."""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path


def timestamp(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise argparse.ArgumentTypeError("use an ISO-8601 timestamp with a timezone") from None
    if parsed.tzinfo is None or parsed.microsecond:
        raise argparse.ArgumentTypeError("timestamp must include a timezone and use whole seconds")
    return parsed.astimezone(timezone.utc)


def page_size(value: str) -> int:
    try:
        number = int(value)
    except ValueError:
        raise argparse.ArgumentTypeError("page size must be an integer from 1 to 200") from None
    if not 1 <= number <= 200:
        raise argparse.ArgumentTypeError("page size must be from 1 to 200")
    return number


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="lastfm", description="Read completed Last.fm scrobbles as JSON (no writes).",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""Workflow:
  auth status                     check local configuration, not API validity
  scrobbles list --start TIME --end TIME --pretty

Credentials: LASTFM_API_KEY and LASTFM_USERNAME in the environment or .env.
Environment values take precedence. --username overrides the default user;
--env-file selects a different dotenv file (default: .env in the working directory).
No password or session secret is needed. Never print or commit API keys.
JSON goes to stdout; errors go to stderr with exit 1 (usage errors: exit 2).
All pages are fetched in a fixed [start,end) window. Now-playing is excluded.
Results retain distinct plays, even if they share a timestamp. No database sync.
See SUBCOMMAND --help for options.""",
    )
    parser.add_argument("--version", action="version", version="%(prog)s 0.1.0")
    commands = parser.add_subparsers(dest="command", required=True)
    auth = commands.add_parser("auth", help="inspect credential configuration")
    auth_commands = auth.add_subparsers(dest="auth_command", required=True)
    status = auth_commands.add_parser("status", help="show metadata only; no network request")
    scrobbles = commands.add_parser("scrobbles", help="read completed listening history")
    subcommands = scrobbles.add_subparsers(dest="scrobble_command", required=True)
    listing = subcommands.add_parser("list", help="fetch every page in an exact time window")
    for command in (status, listing):
        command.add_argument("--username", help="Last.fm username (overrides environment/file)")
        command.add_argument("--env-file", type=Path, default=Path(".env"), help="dotenv file path")
        command.add_argument("--pretty", action="store_true", help="indent JSON output")
    listing.add_argument("--start", type=timestamp, required=True, help="inclusive ISO-8601 time, e.g. 2026-08-01T00:00:00Z")
    listing.add_argument("--end", type=timestamp, required=True, help="exclusive ISO-8601 time, later than start")
    listing.add_argument("--page-size", type=page_size, default=200, help="API page size 1–200 (default: 200); all pages still fetched")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        # Lazy imports let --help work before dependencies are installed.
        from dotenv import dotenv_values
        from .client import LastfmClient, LastfmError
    except ImportError:
        print("Error: install using-lastfm/requirements.txt dependencies first", file=sys.stderr)
        return 1
    key = None
    try:
        values = dotenv_values(args.env_file)
        username = args.username or os.environ.get("LASTFM_USERNAME") or values.get("LASTFM_USERNAME")
        key = os.environ.get("LASTFM_API_KEY") or values.get("LASTFM_API_KEY")
        if args.command == "auth":
            result = {"username": username, "api_key_configured": bool(key), "validated": False}
        else:
            if args.end <= args.start:
                raise ValueError("end must be later than start")
            if not username or not username.strip():
                raise ValueError("provide --username or configure LASTFM_USERNAME")
            if not key:
                raise ValueError("LASTFM_API_KEY is not configured")
            import httpx
            with httpx.Client(timeout=30.0) as http:
                items = LastfmClient(username, key, http, page_size=args.page_size).fetch_scrobbles(start=args.start, end=args.end)
            result = {
                "username": username, "start": args.start.isoformat(), "end": args.end.isoformat(),
                "count": len(items), "items": [item.model_dump(mode="json") for item in items],
            }
        print(json.dumps(result, ensure_ascii=False, indent=2 if args.pretty else None))
        return 0
    except (LastfmError, ValueError, OSError) as error:
        message = str(error)
        if key:
            message = message.replace(key, "[redacted]")
        print(f"Error: {message}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
