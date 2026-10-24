#!/bin/sh
# Put the shipped template worlds into the instance's saves/, once each.
#
# A template is read-only and stays where it was installed; what lands in
# saves/ is a copy, and that copy is the one anybody plays. So a world already
# in saves/ under the same name is never touched: it may be one somebody has
# been living in for a month, and a setup script that reset it would be the
# worst thing this project could do to a person.
#
# The templates carry no player (templates/build.py strips them), so the first
# login in each world starts a fresh one at the world's spawn.
#
# Called by setup.sh. Safe to run on its own, and again.

set -u

repo=$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)
. "$repo/session/prism/common.sh"

templates="$repo/templates"

# Checked as a set before anything is copied: a template that does not match
# what was shipped is not one this script should hand to anybody.
if ! (cd "$templates" && sha256sum --quiet -c SHA256SUMS); then
	echo "templates: checksums do not match templates/SHA256SUMS; copying none" >&2
	exit 1
fi

mkdir -p "$mc/saves" || exit 1
for archive in "$templates"/*.tar.zst; do
	world=$(basename "$archive" .tar.zst)
	if [ -e "$mc/saves/$world" ]; then
		echo "world: $world — already in saves/, left as it is"
		continue
	fi
	# Unpacked beside saves/ and then moved into it, so an unpack that fails
	# halfway leaves nothing behind that would stop the next run trying again.
	tmp=$(mktemp -d "$mc/saves/.seed.XXXXXX") || exit 1
	if tar -C "$tmp" --zstd -xf "$archive" && [ -f "$tmp/$world/level.dat" ]; then
		mv "$tmp/$world" "$mc/saves/$world"
		echo "world: $world — copied from the template"
	else
		echo "world: $world — could not be unpacked; skipped" >&2
	fi
	rm -rf "$tmp"
done
