#!/usr/bin/env python3
"""Run the bundled CLI without installing a package."""
from lastfm_cli.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
