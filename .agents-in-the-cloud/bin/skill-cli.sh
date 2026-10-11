#!/bin/sh
set -eu

# Installed command names are symlinks to this dispatcher. Resolve the target
# so the repository can live anywhere, without changing the caller's cwd.
root=$(dirname "$(dirname "$(dirname "$(readlink -f "$0")")")")
case "$(basename "$0")" in
    bandcamp|lastfm|qobuz)
        name=$(basename "$0")
        exec "$root/.venv/bin/python" "$root/.agents/skills/using-$name/scripts/$name.py" "$@"
        ;;
    exa-search)
        exec node --use-env-proxy "$root/.agents/skills/using-exa-search/scripts/exa-search.mjs" "$@"
        ;;
    read-page)
        exec node --use-env-proxy "$root/.agents/skills/reading-webpages/scripts/read-page.mjs" "$@"
        ;;
    *)
        echo 'Invoke this dispatcher as bandcamp, lastfm, qobuz, exa-search, or read-page.' >&2
        exit 2
        ;;
esac
