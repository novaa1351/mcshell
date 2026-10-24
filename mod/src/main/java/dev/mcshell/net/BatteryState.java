package dev.mcshell.net;

/**
 * The machine's charge, as the daemon last reported it.
 *
 * <p>Drawn on the XP bar. The shell has nowhere else to put a battery gauge,
 * and a laptop you have to guess about is a bad laptop.
 *
 * @param present  false on a machine with no battery. The XP bar then stays
 *                 Minecraft's own, rather than being a gauge for a thing that
 *                 does not exist.
 * @param percent  0..100
 * @param charging current is actually going in
 * @param mains    a cable is plugged in, which is not the same thing: a battery
 *                 held at a charge limit reports "Not charging" all day
 */
public record BatteryState(boolean present, int percent, boolean charging, boolean mains) {
	public static final BatteryState ABSENT = new BatteryState(false, 0, false, false);

	/** 0..1, for the width of the bar. */
	public float fraction() {
		return Math.max(0.0F, Math.min(1.0F, percent / 100.0F));
	}
}
