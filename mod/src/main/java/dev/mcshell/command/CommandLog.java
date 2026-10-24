package dev.mcshell.command;

import java.util.ArrayList;
import java.util.Collections;
import java.util.List;

/**
 * The command bar's transcript: what was run, and what it printed.
 *
 * <p>Everything lands here, whatever the five-line rule decides about chat. The
 * panel is then a complete record rather than a place where only long output
 * ever appears — going looking for what a command said should not depend on how
 * much it happened to say.
 *
 * <p>Client-thread only. It is fed by the tick that drains the socket queue and
 * read by the screen that draws it, both on the render thread; nothing here is
 * synchronised because nothing else touches it.
 */
public final class CommandLog {
	/** Chat scrollback is 100 lines; a panel you scroll deserves more than that. */
	private static final int MAX_LINES = 500;

	public enum Kind {
		/** The echoed command line. */
		COMMAND,
		STDOUT,
		STDERR,
		/** The daemon's word on how a run ended: an exit code, a timeout. */
		NOTE
	}

	public record Line(String text, Kind kind) {
	}

	private final List<Line> lines = new ArrayList<>();
	/**
	 * Bumped on every change.
	 *
	 * <p>The panel wraps lines to its own width, which is expensive enough not
	 * to redo every frame. This is how it knows the wrap it cached is stale.
	 */
	private int revision;
	private String cwd = "";

	public void add(String text, Kind kind) {
		lines.add(new Line(text, kind));
		while (lines.size() > MAX_LINES) {
			lines.removeFirst();
		}
		revision++;
	}

	/** Where the last command ran. Drawn as the panel's header, so `cd` shows. */
	public void setCwd(String cwd) {
		if (cwd != null && !cwd.isEmpty() && !cwd.equals(this.cwd)) {
			this.cwd = cwd;
			revision++;
		}
	}

	public String cwd() {
		return cwd;
	}

	public List<Line> lines() {
		return Collections.unmodifiableList(lines);
	}

	public boolean isEmpty() {
		return lines.isEmpty();
	}

	public int revision() {
		return revision;
	}
}
