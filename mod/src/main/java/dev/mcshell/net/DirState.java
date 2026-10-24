package dev.mcshell.net;

import java.util.List;

/**
 * One directory's subdirectories, exactly as the daemon listed them.
 *
 * <p>Crosses from the socket thread to the render thread, so nothing here is
 * ever mutated after construction.
 *
 * <p>Directories first, then files. Files are leaves — they are here so a
 * directory with things in it does not draw as an empty one — and carry the
 * kind the mod draws an icon for.
 *
 * <p>A listing is a page: {@code total} counts every visible entry and
 * {@code offset} says where this page starts, so the tree can offer a step to
 * the next one rather than dropping a hundred children onto the screen at
 * once. {@code hidden} is how many dotted entries were left out — reported
 * rather than silently dropped, because a home directory has dozens of them
 * and a tree that pretends otherwise is lying about the machine.
 */
public record DirState(String path, String name, List<Entry> entries,
                       int total, int hidden, int offset, String error) {
	/**
	 * One child. {@code kind} is {@code "dir"} or what kind of file it is —
	 * the daemon decides, from a table of extensions, and the mod only knows
	 * which of its icons that names.
	 */
	public record Entry(String name, String path, String kind) {
		public boolean isDir() {
			return "dir".equals(kind);
		}
	}
}
