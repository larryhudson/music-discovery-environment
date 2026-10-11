#!/bin/sh
set -eu

root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
bin_dir=${SKILL_BIN_DIR:-/usr/local/bin}
mkdir -p "$bin_dir"
if [ ! -w "$bin_dir" ]; then
    echo "$bin_dir is not writable; rerun with sudo or set SKILL_BIN_DIR to a writable PATH directory." >&2
    exit 1
fi
for name in bandcamp lastfm qobuz exa-search read-page; do
    ln -sf "$root/.agents-in-the-cloud/bin/skill-cli.sh" "$bin_dir/$name"
done
printf 'Installed skill commands in %s\n' "$bin_dir"
