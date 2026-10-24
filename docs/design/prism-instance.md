# The Prism instance

The world spec, the mods, and the memory settings, with how each was measured.

**How the instance is made (M9).** `session/prism/setup.sh` creates it when
there is none, from `dist/mcshell-<version>.mrpack` (built by
`session/prism/mrpack.py`), through `session/prism/install-pack.py` rather
than Prism's `--import` — which, measured, waits for an OK in a dialog and
names the instance after the file. The pack pins Minecraft 1.21.1, Fabric
Loader 0.19.5 and the mods in `mods.tsv`; everything Prism-specific (Java,
heap, JVM flags, console) and the game's `options.txt` stay `setup.sh`'s,
because a modpack cannot carry them. An existing instance is only ever brought
up to date, never recreated. The sign-in is the one manual step.

Moved out of CLAUDE.md word for word on 2026-10-16, so that file stays
short enough to read in full every session. The reasons below are the
point: read them before changing the thing they describe.

## World setup (Prism instance)

Superflat, void preset, then:

```
/gamerule keepInventory true
/gamerule doMobSpawning false
/gamerule randomTickSpeed 0
/gamerule doWeatherCycle false
/gamerule doDaylightCycle false
/worldborder set 32
```

Mods: Sodium, Lithium, FerriteCore, ModernFix. Render distance 2, framerate cap 30,
`-Xmx1G`.

**The heap's floor is 128M, not 512M, and it gives memory back.** At
`-Xms512m` the JVM kept 520MB of heap for the whole session while a full
collection found 223MB alive. `setup.sh` now sets `-Xms128m` with
`MinHeapFreeRatio=10`, `MaxHeapFreeRatio=30` and `G1PeriodicGCInterval=60000`.
Measured from a fresh start, at the same uptimes with `session/probes/footprint.sh`:
at 16 minutes the heap was 333MB committed instead of 519MB and the game
1,110MB instead of 1,248MB. The cost is about one collection a minute instead
of one every four, averaging 2ms each — 0.07s of pauses over eleven minutes,
against a 33ms frame.

**Two malloc arenas, not up to 128.** `launch.sh` exports
`MALLOC_ARENA_MAX=2`, which Prism passes on to the game. Java objects never
touch malloc; the JIT, the GL driver and LWJGL do, and glibc gave them 16
arenas holding 225MB. Capped: 3 holding 63MB, and the game 977MB instead of
1,110MB at 16 minutes, CPU within noise. Not in Prism's instance settings: Qt's
INI format stripped the quotes out of the JSON Prism stores them in, and the
variable silently never arrived — checked in `/proc/<pid>/environ`, which is
the only place worth checking.

The hotbar holds real `ItemStack`s and the inventory is a real survival inventory
(M8). What the mod intercepts is narrower than it once was: only the gestures
that would change an application stack's count, and `Q` on an application. See
the hotbar rules above.

Hardware note: this is a hybrid-graphics laptop. Minecraft runs on the **Intel iGPU**,
not the 4070. The dGPU is reserved for PRIME-offload of apps launched from the shell.
