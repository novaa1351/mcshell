package dev.mcshell.net;

import java.util.List;

/**
 * One static tab of the Statistics screen, exactly as the daemon described it.
 *
 * <p>Crosses from the socket thread to the render thread, so nothing here is
 * ever mutated after construction.
 *
 * <p>Deliberately just text. The General and Disks tabs are readouts and there
 * is nothing on them to control, so there is nothing for a row type to vary —
 * the mod does not know what a package count is, only how to draw a label
 * beside a value. {@code fraction} is the one exception: a disk is a thing with
 * a proportion, and a bar says that faster than "412 GB of 931 GB" does.
 */
public record StatsState(String tab, List<Row> rows) {
	public static final StatsState EMPTY = new StatsState("", List.of());

	/** @param fraction 0..1, or -1 for a row with no bar */
	public record Row(String group, String label, String value, String detail, float fraction) {
		public boolean hasBar() {
			return fraction >= 0.0F;
		}
	}
}
