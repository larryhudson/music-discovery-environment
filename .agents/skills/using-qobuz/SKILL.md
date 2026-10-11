---
name: using-qobuz
description: "Uses Larry's bundled Qobuz CLI to search music, discover releases, inspect albums and artists, and manage library favorites. Use for Qobuz catalog and library requests."
compatibility: "Python 3.10+ and QOBUZ_STATE_JSON (Amp secret), individual credential env vars, or local auth config."
---

# Using Qobuz

Run `python3 <skill-directory>/scripts/qobuz.py --help` first, resolving `<skill-directory>` to this skill's base directory. Use that same script prefix for every command, including `SUBCOMMAND --help`. Follow the CLI help for authentication, pagination, and authorization before mutations.
