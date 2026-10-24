package dev.mcshell.net;

/**
 * Everything the HUD draws that has no message of its own.
 *
 * <p>Two unrelated things, together because they are the same <em>kind</em> of
 * thing: preferences about drawing. The mod owns neither value nor decision —
 * it owns the pixels — and a message per checkbox would be a message per
 * checkbox forever.
 *
 * <p>Like {@link BatteryState} this crosses from the socket thread to the
 * render thread and is never mutated after construction.
 *
 * @param clock   draw the wall clock at all
 * @param time    "1:27 PM" or "13:27" — already formatted, in the machine's
 *                own locale. The JVM has its own idea of a default locale and
 *                the two disagree often enough to matter, so the daemon
 *                formats and this only prints. See {@code clock.py}.
 * @param date    "Friday, May 1st"
 * @param batteryColor whether the XP-bar gauge may change colour. False pins
 *                it green: the colours mean something — white on mains, red
 *                below 15% — and somebody who does not want the HUD changing
 *                under them can say so.
 */
public record HudState(boolean clock, String time, String date, boolean batteryColor) {
	/**
	 * Before the daemon has said anything. No clock, because there is no time
	 * to draw yet and a HUD that flashes a wrong one on connect is worse than
	 * one that appears a moment late; colour on, because that is the default
	 * and it is what every earlier version of this did.
	 */
	public static final HudState DEFAULT = new HudState(false, "", "", true);

	/** Whether there is actually a clock to draw. */
	public boolean showClock() {
		return clock && !time.isEmpty();
	}
}
