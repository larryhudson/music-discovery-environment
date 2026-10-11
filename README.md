# Music discovery workspace

Listening on **Qobuz**, discovering independent artists through the **Bandcamp wishlist**, and tracking listening on **Last.fm**. Editorial starting points: Pitchfork, Paste, [See/Saw](https://see-saw.fun), and [Post-Trash](https://post-trash.com). Supporting artists financially is part of the goal.

## Bundled skills

| Skill | CLI | Scope |
| --- | --- | --- |
| [using-bandcamp](.agents/skills/using-bandcamp/SKILL.md) | `.venv/bin/python .agents/skills/using-bandcamp/scripts/bandcamp.py` | Public wishlist and pagination |
| [using-qobuz](.agents/skills/using-qobuz/SKILL.md) | `python3 .agents/skills/using-qobuz/scripts/qobuz.py` | Catalog search, releases, artists, library favorites |
| [using-lastfm](.agents/skills/using-lastfm/SKILL.md) | `.venv/bin/python .agents/skills/using-lastfm/scripts/lastfm.py` | Completed scrobbles in an exact time window |

Append `--help` to any CLI, or `SUBCOMMAND --help`, for its options. Bandcamp and Qobuz were copied from the supplied archive. Bandcamp now uses `httpx` for wishlist requests, with an identifying `music-discovery-environment/0.1` User-Agent; its cookie handling and JSON pagination are retained. Qobuz uses the Python standard library. Interactive browser authentication may need additional tooling described by the CLI. Qobuz can mutate favorites: ask before changing the library.

Last.fm adapts the archive's `music_support/lastfm_sync.py`, without bringing in the database or support-accounting application. Its HTTP transport uses standard `httpx` instead of `httpx2`; the original adapter tests are retained and CLI tests added. No credentials were supplied or live account access verified.

## Last.fm setup

```sh
python3 -m venv .venv
.venv/bin/pip install -r .agents/skills/using-lastfm/requirements.txt -r .agents/skills/using-bandcamp/requirements.txt
cp .env.example .env
# Privately edit .env with your LASTFM_API_KEY and LASTFM_USERNAME.
.venv/bin/python .agents/skills/using-lastfm/scripts/lastfm.py auth status
.venv/bin/python .agents/skills/using-lastfm/scripts/lastfm.py scrobbles list \
  --start 2026-08-01T00:00:00Z --end 2026-08-08T00:00:00Z --pretty
```

Get a read-only API key through https://www.last.fm/api/account/create. Environment values override `.env`; `--env-file PATH` selects another file and `--username NAME` overrides the configured username. No Last.fm password/session authentication is needed. `auth status` checks configuration, not credential validity.

The start is inclusive and end exclusive. All pages are fetched with those boundaries frozen, now-playing is excluded, and JSON is written to stdout. Errors go to stderr (exit 1; usage errors exit 2). No files or database are written by Last.fm commands.

### AgentsInTheCloud template configuration

Template Secrets appear in workspace environment variables as placeholders. AgentsInTheCloud substitutes the real credentials into outgoing requests to allowed hosts; the workspace does not receive their raw values.

| Name | Template setting | Allowed host |
| --- | --- | --- |
| `LASTFM_API_KEY` | Secret | `ws.audioscrobbler.com` |
| `LASTFM_USERNAME` | Environment Variable | — |
| `QOBUZ_USER_AUTH_TOKEN` | Secret | `www.qobuz.com` |
| `QOBUZ_APP_ID` | Environment Variable | — |

From a Qobuz state JSON, copy `app_id` into `QOBUZ_APP_ID` and `user_auth_token` into `QOBUZ_USER_AUTH_TOKEN`, without JSON quotes. Remove any `QOBUZ_STATE_JSON` setting because it takes precedence over individual variables. Use a fresh workspace for new template environment variables.

Do not configure `BANDCAMP_STATE_JSON` or `QOBUZ_STATE_JSON` as template Secrets: these CLIs parse JSON locally, and a secret placeholder is not JSON. The imported skills' references to Amp secrets describe their original environment, not AgentsInTheCloud's mechanism. Raw JSON bundles still work as ordinary environment variables outside this mechanism, but contain sensitive credentials.

Public Bandcamp wishlists require no secret or cookies. Use the state JSON's `username` with `wishlist list --username NAME --all --pretty`, or its `fan_id` with `--fan-id ID`.

Never commit credentials, cookies, or exported authentication state. `.env` is ignored by git; do not paste secrets into chat.

## Offline tests

```sh
PYTHONPATH=.agents/skills/using-lastfm/scripts .venv/bin/python -m unittest discover -s .agents/skills/using-lastfm/tests -v
PYTHONPATH=.agents/skills/using-bandcamp/scripts .venv/bin/python -m unittest discover -s .agents/skills/using-bandcamp/tests -v
PYTHONPATH=.agents/skills/using-qobuz/scripts python3 -m unittest discover -s .agents/skills/using-qobuz/tests -v
```

Only the archive's top-level `skills/` were moved into active skills. The music-supporter dashboard/end-of-cycle skills depend on its ledger application, so are intentionally not installed here.
