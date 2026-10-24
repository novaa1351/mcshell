#!/bin/sh
# Build the mod and install the jar into the Prism instance.
#
# CLAUDE.md asks for this step by name, because the alternative is a real
# session that quietly keeps running whatever jar was copied in last and a
# fix that appears not to have worked. Run it after every change to the Java
# side. The *dev* client does not need it — `gradlew runClient` loads the mod
# straight out of the build directory, which is why this gap can go unnoticed.
#
# Safe to run while Minecraft is up; the new jar is picked up at the next
# start, not this one.

set -u

repo=$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)
. "$repo/session/prism/common.sh"
require_instance

"$repo/mod/gradlew" -p "$repo/mod" --console=plain build || exit 1

# The build directory also holds -sources and -dev jars. The remapped one is
# the only one a real client can load.
jar=""
for f in "$repo/mod/build/libs"/mcshell-*.jar; do
	case "$f" in
	*-sources.jar | *-dev.jar | *-dev-shadow.jar) continue ;;
	*'*'*) continue ;;
	esac
	jar="$f"
done

if [ -z "$jar" ]; then
	echo "gradle build produced no jar in $repo/mod/build/libs" >&2
	exit 1
fi

mkdir -p "$mc/mods"

# Clear the old one before copying, and clear it by pattern rather than by
# name: a version bump changes the filename, and two mcshell jars in the
# directory is a duplicate mod id, which Fabric refuses to start with. That
# reads as a crash rather than as a stale install.
rm -f "$mc"/mods/mcshell-*.jar
cp -- "$jar" "$mc/mods/"

echo "installed $(basename -- "$jar") -> $mc/mods/"
