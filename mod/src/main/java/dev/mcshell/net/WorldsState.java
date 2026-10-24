package dev.mcshell.net;

import java.util.List;

/**
 * The Worlds screen's contents: every world, which one the next start opens,
 * and which one is running now. Read every frame; never blocks.
 *
 * <p>Nothing here is decided by the mod. {@code chosen} and {@code running}
 * come from the daemon, which is the only thing that knows either.
 */
public record WorldsState(List<World> worlds, String chosen, String running) {
	public static final WorldsState EMPTY = new WorldsState(List.of(), "", "");

	/**
	 * One world. {@code icon} is a path, or empty when the world has never been
	 * played; {@code iconVersion} changes when the game rewrites the file.
	 */
	public record World(String name, String icon, int iconVersion) {
	}

	/** A world has been chosen that is not the one running. */
	public boolean pending() {
		return !running.isEmpty() && !running.equals(chosen);
	}
}
