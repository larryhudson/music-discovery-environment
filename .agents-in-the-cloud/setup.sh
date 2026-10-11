#!/bin/sh
set -eu

# Resolve the repository root so this also works when invoked manually.
cd "$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"

python3 -m venv .venv
.venv/bin/python -m pip install \
    -r .agents/skills/using-lastfm/requirements.txt \
    -r .agents/skills/using-bandcamp/requirements.txt
