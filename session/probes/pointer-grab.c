/* Who holds the X pointer?
 *
 * XGrabPointer answers AlreadyGrabbed when another client already has it, so
 * asking for the grab and immediately giving it back is a direct read of
 * whether something is holding the pointer for the whole X server.
 *
 * This exists because that state is invisible from everywhere else. Minecraft
 * runs under XWayland, an X grab is server-wide, and a stranded one silently
 * eats the button presses of every other X client while still letting them see
 * pointer motion — a window you can type into and cannot click. Nothing in
 * sway, the daemon or the game's own logs reports it. This does.
 *
 * Build and run with pointer-grab.sh, which compiles it on first use.
 */
#include <X11/Xlib.h>
#include <stdio.h>

int main(void) {
    Display *d = XOpenDisplay(NULL);
    if (!d) {
        puts("no display - is DISPLAY set, and is XWayland running?");
        return 2;
    }

    int s = XGrabPointer(d, DefaultRootWindow(d), True, ButtonPressMask,
                         GrabModeAsync, GrabModeAsync, None, None, CurrentTime);
    if (s == GrabSuccess) {
        XUngrabPointer(d, CurrentTime);
    }
    XFlush(d);
    XCloseDisplay(d);

    switch (s) {
        case GrabSuccess:     puts("FREE  - nobody holds the pointer");          break;
        case AlreadyGrabbed:  puts("HELD  - another client holds the pointer");  break;
        case GrabFrozen:      puts("FROZEN");                                    break;
        case GrabNotViewable: puts("NOTVIEWABLE");                               break;
        default:              printf("status %d\n", s);
    }
    return s == GrabSuccess ? 0 : 1;
}
