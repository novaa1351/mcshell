package dev.mcshell.net;

import java.util.List;

/**
 * The last catalog page the daemon sent, exactly as it described it.
 *
 * <p>Like {@link TaskbarState}, this crosses from the socket thread to the
 * render thread through an {@link java.util.concurrent.atomic.AtomicReference},
 * so it must never be mutated after construction.
 *
 * <p>There is one of these, not one per tab. The daemon answers a
 * {@code catalog_query} with the apps that match it, and the browser renders
 * whatever arrived last — switching tabs is a new query, not a lookup in a
 * cache the mod keeps. The daemon owns what apps exist; the mod owns nothing.
 */
public record CatalogState(List<Item> items) {
	/** What we draw before the daemon has answered: nothing. */
	public static final CatalogState EMPTY = new CatalogState(List.of());

	/**
	 * One installed application.
	 *
	 * @param id       desktop file id, e.g. {@code "firefox.desktop"} — the
	 *                 handle every other message uses to name an app
	 * @param name     display name, already localised by the daemon
	 * @param iconPath absolute filesystem path to an icon, or null
	 * @param tab      which catalog tab it belongs in
	 */
	public record Item(String id, String name, String iconPath, String tab) {
	}
}
