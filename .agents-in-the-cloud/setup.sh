#!/bin/sh
set -eu

# Resolve the repository root so this also works when invoked manually.
cd "$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"

python3 -m venv .venv
.venv/bin/python -m pip install \
    -r .agents/skills/using-lastfm/requirements.txt \
    -r .agents/skills/using-bandcamp/requirements.txt

# Keep Node dependencies local to each skill. Chromium is provided by the workspace.
npm ci --prefix .agents/skills/using-exa-search
npm ci --prefix .agents/skills/reading-webpages

# Persistent PATH commands for agents and terminals (no shell activation needed).
sh .agents-in-the-cloud/install-cli.sh
