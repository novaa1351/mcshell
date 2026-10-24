# The Accessibility screen is the shell's own settings

The General page, and the sound picker that opens a real file chooser.

Moved out of CLAUDE.md word for word on 2026-10-16, so that file stays
short enough to read in full every session. The reasons below are the
point: read them before changing the thing they describe.

## The Accessibility screen is the shell's own settings

The last vanilla options screen with nothing of ours behind it, and the
nearest thing the game has to the subject: what does this shell draw, and
what does it record. Unlike Statistics and Advancements, **Minecraft's own
screen is not buried** — it is one button away in the bottom-left, exactly
like Sound, Video and Controls. Narrator, text background and high contrast
are real settings for a real player, and this world is played in.

**Vanilla's *Accessibility Guide* button is gone.** It is the one options
screen whose footer holds two buttons rather than one, and the second landed
exactly where the shell's lane switch already sits — the two drew through
each other. It is removed rather than moved: it opens minecraft.net, which in
this shell means a browser window flying up over the desktop from a settings
screen, to read a marketing page about the settings behind it. Dropped at the
point vanilla adds it (`AccessibilityOptionsScreenMixin`), not from the built
screen, because a `DirectionalLayoutWidget` computes its positions once from
its children — remove the button afterwards and its gap stays. Never adding it
leaves Done as the row's only child, centred like every other options screen.

Seven rows, and every one of them exists because somebody could reasonably
want it off:

- **The clock**, and whether it is 12- or 24-hour.
- **Whether the battery gauge may change colour.** Off pins it green.
- **What noise the volume keys make**, including none. Its own group rather
  than filed under Notifications: a notification is something an application
  asked for, and this is the machine answering the person holding it.
- **Whether notifications appear at all**, and whether they make a sound —
  the same switch as the one on the Sound page, which is two doors onto one
  value rather than two values.
- **What that sound is.**
- **Whether screen time is counted.** Off stops counting and erases nothing:
  what is banked is what the machine actually did.

**The sound is chosen in a real window.** The game client is the wrong place
to type a path into, and there is no browse widget to build one from. (There
was no text field at all when this was written; Controls grew one in M8, and
it changes nothing here — a path is not something anybody should be typing
out by hand when a picker exists.) The desktop already has the answer and the
shell
already has the pattern — sudo's prompt goes to the compositor, not to chat —
so the button opens `org.freedesktop.portal.FileChooser`, the same file
chooser every other application on the machine opens. Measured before it was
written: xdg-desktop-portal-gtk is running and answering. The row greys while
the dialog is open, because a button that is already doing something should
say so, and `set` returns at once rather than holding the socket for as long
as somebody browses.

**A chosen sound is cut off at five seconds.** The level-up is 1.5s; an album
track picked by accident would otherwise outlive the toast it belonged to by
a factor of sixty. It is played once when it is chosen, because the point of
picking a sound is to find out what it sounds like.
