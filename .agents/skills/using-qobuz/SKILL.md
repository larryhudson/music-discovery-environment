---
name: using-qobuz
description: "Uses Larry's bundled Qobuz CLI to search music, discover releases, inspect albums and artists, and manage library favorites. Use for Qobuz catalog and library requests."
compatibility: "Python 3.10+ and QOBUZ_STATE_JSON (Amp secret), individual credential env vars, or local auth config."
---

# Using Qobuz

Workspace setup installs `qobuz` on PATH, using the repository's Python virtual environment. Run `qobuz --help` first, then use `qobuz SUBCOMMAND --help` for command options. Follow the CLI help for authentication, pagination, and authorization before mutations. Outside this workspace, use `python3 <skill-directory>/scripts/qobuz.py`; resolve `<skill-directory>` to this skill's base directory.

## Album save notes

With explicit user permission to change favorites, use:

```sh
qobuz add album ALBUM_ID --reason 'Why this album fits; suggested first tracks'
```

Every successful album/release add records `album_id`, `album_name`, `artist_name`, `link`, `reason`, `saved_at`, and `updated_at` in **`qobuz-saves.json` at this repository's root**, regardless of the caller's working directory. Reasons are local notes, not uploaded to Qobuz. The file is intended to be versioned in the repo; it contains listening notes, not credentials.

The JSON envelope is `{"version": 1, "saves": [...]}`. One record per album ID: re-saving with a reason replaces the note; omitting `--reason` retains an existing note (or records null for a new album). Empty reasons are rejected. Only album/release saves support notes. `--saves-file PATH` overrides `QOBUZ_SAVES_FILE`, which overrides the default. `--raw` still records notes but returns only the API response.

Writes are locked across concurrent CLI processes and atomically replaced. Invalid existing JSON or missing album metadata blocks the remote mutation. Failed/unconfirmed Qobuz saves do not write a record. If Qobuz succeeds but writing notes fails, the command exits with an explicit partial-success error; retry the same add to record the note without duplicating its local entry.

This is a save-notes journal, not a live mirror of favorites: removing a favorite retains its note, and existing favorites are not automatically backfilled. Check the library separately when current membership matters.
