---
name: using-qobuz
description: "Uses Larry's bundled Qobuz CLI to search music, discover releases, inspect albums and artists, and manage library favorites. Use for Qobuz catalog and library requests."
compatibility: "Python 3.10+ and QOBUZ_STATE_JSON (Amp secret), individual credential env vars, or local auth config."
---

# Using Qobuz

Workspace setup installs `qobuz` on PATH, using the repository's Python virtual environment. Run `qobuz --help` first, then use `qobuz SUBCOMMAND --help` for command options. Follow the CLI help for authentication, pagination, and authorization before mutations. Outside this workspace, use `python3 <skill-directory>/scripts/qobuz.py`; resolve `<skill-directory>` to this skill's base directory.
