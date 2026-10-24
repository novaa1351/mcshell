package dev.mcshell.net;

import java.util.List;

/**
 * One thing the daemon said about a running command.
 *
 * <p>Queued by the socket thread and drained on the client tick. It carries the
 * message as it arrived and decides nothing: whether a run's output belongs in
 * chat or in the overview panel is settled later, on the thread that is allowed
 * to touch either.
 *
 * @param kind   which of the four messages this is
 * @param cmd    the run this belongs to, numbered by the daemon
 * @param text   START only: the command line, as submitted
 * @param cwd    START only: the directory it is running in
 * @param lines  OUTPUT only: a batch of output, already stripped of ANSI
 * @param stderr OUTPUT only: this batch came from stderr
 * @param code   END only: exit status, negative for a signal
 * @param note   END only: why it ended, when that is worth saying; else empty
 */
public record CommandEvent(
		Kind kind,
		int cmd,
		String text,
		String cwd,
		List<String> lines,
		boolean stderr,
		int code,
		String note) {

	public enum Kind {
		START,
		OUTPUT,
		END,
		/** {@code chat_clear}: empty the chat, as F3+D does. */
		CLEAR
	}

	public static CommandEvent start(int cmd, String text, String cwd) {
		return new CommandEvent(Kind.START, cmd, text, cwd, List.of(), false, 0, "");
	}

	public static CommandEvent output(int cmd, List<String> lines, boolean stderr) {
		return new CommandEvent(Kind.OUTPUT, cmd, "", "", List.copyOf(lines), stderr, 0, "");
	}

	public static CommandEvent clear(int cmd) {
		return new CommandEvent(Kind.CLEAR, cmd, "", "", List.of(), false, 0, "");
	}

	public static CommandEvent end(int cmd, int code, String note) {
		return new CommandEvent(Kind.END, cmd, "", "", List.of(), false, code, note);
	}
}
