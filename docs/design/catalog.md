# The catalog browser

The creative-style app drawer, its tabs, and how new apps appear.

Moved out of CLAUDE.md word for word on 2026-10-16, so that file stays
short enough to read in full every session. The reasons below are the
point: read them before changing the thing they describe.

## Catalog browser
- Reached the way creative mode reaches its item list: `E` opens the **real survival
  inventory**, and a **creative-style tab** tucked under its top-left edge — a real
  vanilla tab sprite with a chest on it — opens the catalog. `E` is not a catalog
  key. Keeping the survival inventory is the point — the shell is a survival
  world, not a creative one.
- **The chrome is vanilla's, to the pixel** (M8): `tab_items.png`, the creative
  tab sprites, the creative slot highlight, and the geometry copied out of
  `CreativeInventoryScreen` rather than approximated. Applications draw as real
  `mcshell:app` stacks, so the catalog and the hotbar cannot drift apart.
- **Tabs carry items, never words.** Minecraft has never labelled a creative tab
  in text, and a row of boxes reading "Games / Web / Work" is the loudest
  possible tell that this is not part of the game. Sword, compass, crafting
  table, jukebox, redstone, barrel, spyglass — hovering one names it. The
  mapping is a line each in `CatalogScreen.TABS`.
- The inventory's 27 slots hold real Minecraft items, like any survival world's
  (M8). Only the 9 hotbar slots are *assignable*; the catalog is already the app
  drawer, so a middle tier would be a second place to keep apps with no reason to
  prefer either. An application dragged up into the 27 unassigns its slot.
- Nothing draws the hotbar row inside the inventory any more — the applications
  are real items in real slots, so the screen draws them itself.
- Backed by `.desktop` files from `/usr/share/applications` and
  `~/.local/share/applications`, parsed with `pyxdg`.
- **An app installed mid-session appears without a restart.** The catalog
  used to be read once, at daemon start, so a new app existed nowhere — not
  in the catalog, and not on the hotbar either, since a window borrows a slot
  only if the catalog can name it. Now `Catalog.follow` stats the
  applications directories every 2s (five `stat`s; Flatpak's export
  directories count even before they exist), waits until they have been still
  for 2s — an install is many writes — and rescans on a worker thread, because
  a scan is 0.4–0.75s and the loop carries the pointer handshake. Each
  client's last search is answered again unasked, so an open catalog fills in
  with no mod change. Measured on the live daemon: **3.5–4.7s** from the
  `.desktop` file landing to the app on screen, SVG icons rasterised.
  - **pyxdg's icon caches are cleared before every rescan.** It decides when
    to re-read an icon directory from the theme's *top* directory's mtime,
    shared across base directories, which an icon added to an existing
    `48x48/apps` does not move. Measured: a fresh process found a new icon
    the running daemon did not. Clearing costs nothing measurable, and icon
    lookups now take a lock, since the rescan thread and the notification
    server share those module-level caches.
  - **A new app with no icon gets a second look 6s later**, for an icon that
    lands after its `.desktop` file. Measured: placeholder at 4.7s, real icon
    at 11.5s.
  - **Not seen: a `.desktop` file edited in place.** Polling directory mtimes
    catches every create, remove and rename — every way a package manager
    touches one — but not an edit. That is not an install.
- Freedesktop `Categories=` map to six tabs: **Games, Browsing, Productivity, Media,
  Tech, Misc** — plus Search, which makes seven, exactly the number vanilla fits
  in a row. Deliberately not the freedesktop main categories — those are written
  for menu editors, and name a browser "Network" and a terminal "System". The
  priority-ordered mapping lives in `catalog.py`; it is data, and re-tagging an app is
  a one-line change there.
- Search tab = fuzzy app search. Not a category — it queries across all of them.
