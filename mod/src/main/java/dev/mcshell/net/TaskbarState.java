package dev.mcshell.net;

import java.util.List;

/**
 * An immutable snapshot of the hotbar, exactly as the daemon last described it.
 *
 * <p>Handed between the socket thread and the render thread through an
 * {@link java.util.concurrent.atomic.AtomicReference}, so it must never be
 * mutated after construction.
 */
public record TaskbarState(List<Slot> slots) {
	/** Nine empty slots: what we draw before the daemon has said anything. */
	public static final TaskbarState EMPTY = new TaskbarState(List.of());

	/**
	 * One hotbar slot.
	 *
	 * @param index    1-based slot number, matching the key that selects it
	 * @param app      desktop file id, or null when the slot is unassigned
	 * @param name     what the app calls itself, or null when it is no longer
	 *                 installed; the item is held under this name
	 * @param iconPath absolute filesystem path to an icon, or null
	 * @param running  the app has at least one open window
	 * @param windows  how many windows it has open
	 * @param focused  one of its windows currently has focus
	 * @param launching spawned, but no window has appeared yet
	 */
	public record Slot(
			int index,
			String app,
			String name,
			String iconPath,
			boolean running,
			int windows,
			boolean focused,
			boolean launching) {

		public boolean assigned() {
			return app != null && !app.isEmpty();
		}

		/**
		 * The name to hold this application under.
		 *
		 * <p>Falls back to the desktop id: a slot assigned to something no
		 * longer installed has no name to send, and
		 * {@code libreoffice-calc.desktop} is more use on a broken slot than a
		 * blank label.
		 */
		public String displayName() {
			if (name != null && !name.isEmpty()) {
				return name;
			}
			return app == null ? "" : app;
		}
	}

	/** The slot drawn at hotbar position {@code i} (0-based), or null. */
	public Slot at(int i) {
		int wanted = i + 1;
		for (Slot slot : slots) {
			if (slot.index() == wanted) {
				return slot;
			}
		}
		return null;
	}
}
