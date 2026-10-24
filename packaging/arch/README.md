# The Arch package

`PKGBUILD` here is the source of the AUR package `mcshell`. It builds from a
tagged GitHub release: the source tarball, the mod's jar and the `.mrpack`,
which the release workflow publishes together. The AUR's own git repository
gets a copy of this file and its `.SRCINFO`; this one is where it is edited.

You need `pacman-contrib` (for `updpkgsums`), `namcap` and `devtools`:

```bash
sudo pacman -S --needed pacman-contrib namcap devtools
```

## A new release

1. Set the version in `mod/gradle.properties` (`mod_version`) and
   `daemon/pyproject.toml` (`version`). The release workflow refuses a tag
   that disagrees with either.
2. Tag and push, and wait for the release to show its four files:

   ```bash
   git tag -a v0.1.0 -m "MCShell 0.1.0" && git push origin v0.1.0
   ```

3. Here, set `pkgver` to the new version and `pkgrel=1`, then fill the sums
   from the published files and regenerate `.SRCINFO`:

   ```bash
   cd packaging/arch
   updpkgsums
   makepkg --printsrcinfo > .SRCINFO
   ```

4. Test it (below), then commit `PKGBUILD` and `.SRCINFO` here.
5. Publish to the AUR (below).

A fix to the packaging alone, with no new release: bump `pkgrel` instead,
and skip steps 1 and 2.

## Testing a build

```bash
cd packaging/arch
namcap PKGBUILD
extra-x86_64-build               # builds in a clean chroot: catches a missing dependency
namcap mcshell-*.pkg.tar.zst
```

The daemon's test suite can run against the built package rather than the
checkout:

```bash
mkdir /tmp/pkg && tar -xf mcshell-*.pkg.tar.zst -C /tmp/pkg
MCSHELL_TEST_INSTALLED=/tmp/pkg daemon/.venv/bin/python -m pytest -q daemon/tests
```

The real test is installing it on a clean machine (the VM's snapshot):
`sudo pacman -U mcshell-*.pkg.tar.zst`, then `mcshell setup`, sign in to
Prism, `mcshell check`, and log in.

A machine that installed MCShell from a checkout has
`/usr/share/wayland-sessions/mcshell.desktop` already, which pacman will
refuse to overwrite. Remove it first (the README's uninstall steps).

## Publishing to the AUR

Once: make an account at <https://aur.archlinux.org>, add your SSH public key
under *My Account*, and clone the package's AUR repository (empty the first
time; the name is reserved by the first push):

```bash
git clone ssh://aur@aur.archlinux.org/mcshell.git ~/aur/mcshell
```

Each release:

```bash
cp packaging/arch/PKGBUILD packaging/arch/.SRCINFO ~/aur/mcshell/
cd ~/aur/mcshell
git add PKGBUILD .SRCINFO
git commit -m "Update to 0.1.0"
git push
```

The AUR repository holds only those two files; nothing else may be pushed
there.
