---
name: using-lastfm
description: "Reads completed Last.fm listening history with the bundled JSON CLI. Use for scrobble queries over a time window and listening-history analysis."
compatibility: "Python 3.10+ with requirements.txt dependencies. LASTFM_API_KEY and LASTFM_USERNAME from environment or a local dotenv file; --username overrides the user."
---

# Using Last.fm

Workspace setup installs `lastfm` on PATH, using the repository's Python virtual environment. Run `lastfm --help` first, then use `lastfm SUBCOMMAND --help` for command options. Follow the CLI help for configuration, output, and pagination. Outside this workspace, use `python3 <skill-directory>/scripts/lastfm.py` with dependencies installed; resolve `<skill-directory>` to this skill's base directory. See the root README for setup.

Use `auth status` to inspect configuration without revealing credentials; this does not validate the key against Last.fm. `scrobbles list` requires explicit timezone-aware, whole-second `--start` and `--end` timestamps. It fetches all pages in the fixed half-open window `[start,end)`, excluding now-playing. Output is `{username,start,end,count,items}`; each item retains the source artist, album, track, MBIDs, Last.fm URL, and UTC play time. Empty album/MBIDs become null. Distinct plays sharing a timestamp are retained.

This tool is read-only: it does not scrobble, love tracks, persist a ledger, or infer purchases from listening. Avoid huge windows without asking; every API page is fetched. Treat listening history as personal data. Never print, log, or commit API keys or authentication bundles. See `requirements.txt` for dependencies and `tests/` for offline coverage.
