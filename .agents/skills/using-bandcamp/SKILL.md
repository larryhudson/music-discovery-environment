---
name: using-bandcamp
description: "Reads Larry's Bandcamp wishlist with the bundled CLI. Use for Bandcamp wishlist queries and pagination."
compatibility: "Python 3.10+ with httpx (requirements.txt). BANDCAMP_STATE_JSON (Amp secret) or local config supplies the default fan identity and optional cookies."
---

# Using Bandcamp

Run `python3 <skill-directory>/scripts/bandcamp.py --help` first, resolving `<skill-directory>` to this skill's base directory. Use that same script prefix for every command, including `SUBCOMMAND --help`. Follow the CLI help for authentication, output, and pagination.

Install dependencies with `python3 -m pip install -r <skill-directory>/requirements.txt`, or use the workspace `.venv/bin/python`. Wishlist requests use httpx with the identifying User-Agent `music-discovery-environment/0.1`; no HTML scraping.
