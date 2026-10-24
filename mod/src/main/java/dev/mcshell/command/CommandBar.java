package dev.mcshell.command;

import dev.mcshell.MCShellClient;
import dev.mcshell.net.CommandEvent;
import dev.mcshell.net.DaemonConnection;
import net.fabricmc.fabric.api.client.message.v1.ClientSendMessageEvents;
import net.minecraft.client.MinecraftClient;
import net.minecraft.text.Text;
import net.minecraft.util.Formatting;

import java.util.ArrayList;
import java.util.List;

/**
 * Minecraft's chat, used as the shell's command bar.
 *
 * <p>Every plain chat line is a command: the outgoing message is cancelled and
 * sent to the daemon instead. Minecraft's own slash commands are untouched and
 * never reach us — {@code /gamerule} still means what it always did.
 *
 * <p>This class owns the one decision the mod is supposed to make about output.
 * CLAUDE.md puts the hybrid rule on this side of the socket deliberately: the
 * daemon emits the same messages either way, and where they are drawn is a
 * question about the screen, which is ours.
 *
 * <p>The rule, with output that streams: hold a run's lines until it ends. Five
 * or fewer, and they go to chat. The moment a run crosses five while still
 * running, the overview opens and the rest of the run fills the panel live —
 * waiting for the end to open it would mean staring at nothing during the build
 * that most wanted the panel.
 */
public final class CommandBar {
	/** CLAUDE.md's threshold: at most this many lines belong in chat. */
	private static final int CHAT_LINES = 5;

	private final DaemonConnection connection;
	private final CommandLog log;

	/** The run being collected, or -1 when nothing is running. */
	private int pendingCmd = -1;
	private final List<CommandLog.Line> pending = new ArrayList<>();
	/** This run has outgrown chat; its output is going to the panel. */
	private boolean promoted;
	private boolean wasConnected;

	public CommandBar(DaemonConnection connection, CommandLog log) {
		this.connection = connection;
		this.log = log;
	}

	public void register() {
		ClientSendMessageEvents.ALLOW_CHAT.register(this::submit);
	}

	/**
	 * @return false always — the message is a command, so it never goes to the
	 *         world. Returning true would send it to the integrated server,
	 *         which would echo shell commands into chat as if they were talk.
	 */
	private boolean submit(String message) {
		String text = message.strip();
		if (text.isEmpty()) {
			return false;
		}
		if (!connection.connected()) {
			// The command would be queued into a socket nothing is reading, and
			// vanish. Say so rather than swallowing it silently.
			chat(Text.translatable("mcshell.command.disconnected").formatted(Formatting.RED));
			return false;
		}
		connection.commandSubmit(text);
		return false;
	}

	/** Drain what the daemon has said since the last tick. */
	public void tick() {
		boolean connected = connection.connected();
		if (wasConnected && !connected && pendingCmd != -1) {
			// The daemon went away mid-run: no `command_end` is ever coming, so
			// close the run off here rather than holding its lines forever.
			flush();
			pendingCmd = -1;
			log.add("[daemon disconnected]", CommandLog.Kind.NOTE);
			chat(Text.translatable("mcshell.command.disconnected").formatted(Formatting.RED));
		}
		wasConnected = connected;

		CommandEvent event;
		while ((event = connection.pollCommand()) != null) {
			switch (event.kind()) {
				case START -> start(event);
				case OUTPUT -> output(event);
				case END -> end(event);
				case CLEAR -> clear();
			}
		}
	}

	private void start(CommandEvent event) {
		// A previous run that never ended (a daemon restart between messages)
		// must not swallow this one's output.
		flush();
		pendingCmd = event.cmd();
		promoted = false;
		log.setCwd(event.cwd());
		log.add("$ " + event.text(), CommandLog.Kind.COMMAND);
		// Echoed immediately, and in chat even when the output will end up in
		// the panel: cancelling the chat message means nothing else confirms
		// that the line was taken, and a command with no output at all would
		// otherwise look ignored.
		chat(Text.literal("$ " + event.text()).formatted(Formatting.GRAY));
	}

	private void output(CommandEvent event) {
		CommandLog.Kind kind = event.stderr() ? CommandLog.Kind.STDERR : CommandLog.Kind.STDOUT;
		for (String line : event.lines()) {
			log.add(line, kind);
			if (promoted) {
				continue;
			}
			pending.add(new CommandLog.Line(line, kind));
			if (pending.size() > CHAT_LINES) {
				promote();
			}
		}
	}

	private void end(CommandEvent event) {
		if (event.cmd() != pendingCmd && pendingCmd != -1) {
			// Not the run we are holding. The daemon runs one at a time, so
			// this only happens across a reconnect; keep what we have.
			return;
		}
		// Held lines first, then the verdict: an exit code printed above the
		// error that explains it reads backwards.
		flush();
		String note = describe(event);
		if (!note.isEmpty()) {
			log.add(note, CommandLog.Kind.NOTE);
			// Always in chat, even for a promoted run whose output went to the
			// panel: a command that failed should say so where you are looking,
			// not only where you might look.
			chat(Text.literal(note).formatted(Formatting.YELLOW));
		}
		pendingCmd = -1;
	}

	/**
	 * {@code clear}: what F3+D does, read out of the 1.21.1 bytecode —
	 * {@code ChatHud.clear(false)}. False keeps the sent-message history, so
	 * the up arrow still recalls what was typed, as a terminal's clear does.
	 * The panel's transcript is not touched; that is the overview, not chat.
	 */
	private void clear() {
		MinecraftClient client = MinecraftClient.getInstance();
		if (client.world != null) {
			client.inGameHud.getChatHud().clear(false);
		}
	}

	/** The one-line verdict on a finished run, or empty when it simply worked. */
	private static String describe(CommandEvent event) {
		boolean failed = event.code() != 0;
		if (!failed && event.note().isEmpty()) {
			return "";
		}
		if (event.note().isEmpty()) {
			return "[exit " + event.code() + "]";
		}
		return failed
				? "[exit " + event.code() + ", " + event.note() + "]"
				: "[" + event.note() + "]";
	}

	/** Put a short run's held lines into chat. */
	private void flush() {
		if (!promoted) {
			for (CommandLog.Line line : pending) {
				chat(Text.literal(line.text()).formatted(
						line.kind() == CommandLog.Kind.STDERR ? Formatting.RED : Formatting.WHITE));
			}
		}
		pending.clear();
		promoted = false;
	}

	/** This run is too long for chat. Open the panel and let it fill live. */
	private void promote() {
		promoted = true;
		pending.clear();
		chat(Text.translatable("mcshell.command.in_overview").formatted(Formatting.DARK_GRAY));
		MCShellClient.showOverview();
	}

	private void chat(Text text) {
		MinecraftClient client = MinecraftClient.getInstance();
		// No chat hud before a world is loaded. The transcript still has it.
		if (client.world != null) {
			client.inGameHud.getChatHud().addMessage(text);
		}
	}
}
