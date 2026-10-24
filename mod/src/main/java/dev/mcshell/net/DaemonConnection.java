package dev.mcshell.net;

import com.google.gson.JsonArray;
import com.google.gson.JsonElement;
import com.google.gson.JsonObject;
import com.google.gson.JsonParser;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import java.io.BufferedReader;
import java.io.IOException;
import java.io.InputStreamReader;
import java.io.OutputStream;
import java.net.StandardProtocolFamily;
import java.net.UnixDomainSocketAddress;
import java.nio.channels.Channels;
import java.nio.channels.SocketChannel;
import java.nio.charset.StandardCharsets;
import java.nio.file.Path;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import java.util.Queue;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.BlockingQueue;
import java.util.concurrent.ConcurrentLinkedQueue;
import java.util.concurrent.LinkedBlockingQueue;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicReference;

/**
 * The mod's half of the daemon protocol: newline-delimited JSON over a unix
 * socket.
 *
 * <p>Runs entirely off the render thread. Inbound state lands in an
 * {@link AtomicReference} the renderer reads without locking; outbound events
 * go on a queue. Nothing here blocks Minecraft, and a dead daemon costs a
 * reconnect timer, not a frame.
 *
 * <p>Java NIO has supported unix sockets since 16, so this needs no JNI and no
 * dependencies.
 *
 * <p>Deliberately free of Minecraft imports, so the transport can be exercised
 * headlessly against a running daemon. Real stack traces beat crash logs.
 */
public final class DaemonConnection {
	private static final Logger LOG = LoggerFactory.getLogger("mcshell.daemon");

	private static final int PROTO = 1;
	private static final String MC_VERSION = "1.21.1";

	/** The daemon is restarted constantly during development; reconnect politely. */
	private static final long BACKOFF_MIN_MS = 250;
	private static final long BACKOFF_MAX_MS = 5_000;

	/** Bounded so a daemon that stops reading cannot grow the queue without limit. */
	private static final int OUTBOUND_CAPACITY = 256;

	private final Path socketPath;
	private final AtomicReference<TaskbarState> state = new AtomicReference<>(TaskbarState.EMPTY);
	/** Last unread `overview` push, or null. Set on the socket thread, drained on the client tick. */
	private final AtomicReference<Boolean> overviewRequest = new AtomicReference<>();

	/** Last unread `focus` push: whether the game is the focused window, or null. */
	private final AtomicReference<Boolean> focusRequest = new AtomicReference<>();
	/** A pending save_world, by id. Handed to the client tick, which owns the server. */
	private final AtomicReference<Integer> saveRequest = new AtomicReference<>();
	private final AtomicReference<CatalogState> catalog = new AtomicReference<>(CatalogState.EMPTY);
	/** The battery, for the XP bar. Read every frame by the HUD; never blocks. */
	private final AtomicReference<BatteryState> battery = new AtomicReference<>(BatteryState.ABSENT);
	/** The clock and the gauge's colour. Read every frame, like the battery. */
	private final AtomicReference<HudState> hud = new AtomicReference<>(HudState.DEFAULT);
	/** The Statistics screen's static tabs, keyed by tab name. */
	private final Map<String, StatsState> stats = new ConcurrentHashMap<>();
	/** The Worlds screen's list. Asked for when the screen opens. */
	private final AtomicReference<WorldsState> worlds = new AtomicReference<>(WorldsState.EMPTY);
	/** The live sample, replaced once a second while the task manager is open. */
	private final AtomicReference<ProcessState> processes = new AtomicReference<>(ProcessState.EMPTY);
	/**
	 * The last schema for each settings page.
	 *
	 * <p>A map rather than one reference because pages are pushed
	 * independently: PipeWire saying something about audio must not blank the
	 * video page a screen happens to be showing.
	 */
	private final Map<String, SettingsState> settings = new ConcurrentHashMap<>();

	/**
	 * Errors the daemon sent, for whoever is on screen to show.
	 *
	 * <p>They used to go only to the log. A refused setting then looked exactly
	 * like a setting that did nothing, which is the worst of both: the daemon
	 * had said why, and nobody could hear it.
	 */
	private final Queue<String> errors = new ConcurrentLinkedQueue<>();

	/**
	 * Command bar traffic, in arrival order, waiting for the client tick.
	 *
	 * <p>A queue rather than a latest-value reference like the others: the
	 * taskbar is a state snapshot where only the newest matters, but output is a
	 * sequence, and dropping the middle of a build's output would be worse than
	 * useless.
	 */
	private final Queue<CommandEvent> commands = new ConcurrentLinkedQueue<>();

	/**
	 * Directory listings, in arrival order, waiting for the file tree.
	 *
	 * <p>A queue rather than a map keyed on path: the same directory is listed
	 * again to step to its next page, and a map would let the second answer
	 * quietly replace the first before the screen had read either.
	 */
	private final Queue<DirState> dirs = new ConcurrentLinkedQueue<>();
	private final BlockingQueue<String> outbound = new LinkedBlockingQueue<>(OUTBOUND_CAPACITY);

	private volatile boolean running;
	private volatile boolean connected;
	/**
	 * Bumped on every successful connect.
	 *
	 * <p>Only {@code world_ready} needs this. It is sent once per
	 * connection rather than once per run, because a daemon restarted with
	 * {@code $mod+Shift+d} comes back knowing nothing and would otherwise
	 * leave its boot screen up over a desktop that is already there.
	 */
	private volatile long epoch;
	private volatile SocketChannel channel;
	private Thread thread;

	public DaemonConnection(Path socketPath) {
		this.socketPath = socketPath;
	}

	/** Where the daemon listens, following the same rule the daemon uses. */
	public static Path defaultSocketPath() {
		String runtime = System.getenv("XDG_RUNTIME_DIR");
		if (runtime == null || runtime.isEmpty()) {
			runtime = "/run/user/" + uid();
		}
		return Path.of(runtime, "mcshell.sock");
	}

	private static String uid() {
		// No portable API for this; the daemon falls back the same way.
		String user = System.getProperty("user.name", "");
		try {
			Process p = new ProcessBuilder("id", "-u").start();
			try (BufferedReader r = new BufferedReader(
					new InputStreamReader(p.getInputStream(), StandardCharsets.UTF_8))) {
				String line = r.readLine();
				if (line != null && !line.isBlank()) {
					return line.trim();
				}
			}
		} catch (IOException ignored) {
			// fall through
		}
		return user;
	}

	// -- lifecycle ---------------------------------------------------------

	public void start() {
		if (thread != null) {
			return;
		}
		running = true;
		thread = new Thread(this::run, "mcshell-daemon");
		thread.setDaemon(true);
		thread.start();
	}

	public void stop() {
		running = false;
		closeQuietly();
		if (thread != null) {
			thread.interrupt();
			thread = null;
		}
	}

	public TaskbarState state() {
		return state.get();
	}

	/** The last catalog page the daemon sent. Empty until something asks. */
	public SettingsState settings(String page) {
		return settings.getOrDefault(page, SettingsState.EMPTY);
	}

	public CatalogState catalog() {
		return catalog.get();
	}

	public BatteryState battery() {
		return battery.get();
	}

	public HudState hud() {
		return hud.get();
	}

	public StatsState stats(String tab) {
		return stats.getOrDefault(tab, StatsState.EMPTY);
	}

	public WorldsState worlds() {
		return worlds.get();
	}

	public ProcessState processes() {
		return processes.get();
	}

	public boolean connected() {
		return connected;
	}

	/** Which connection this is. See the field. */
	public long epoch() {
		return epoch;
	}

	/**
	 * Tell the daemon the world is on screen, so it can take the boot screen
	 * down.
	 *
	 * <p>Nothing else can say this. {@code hello} arrives while the client is
	 * still loading a world, and the compositor has seen Minecraft's window for
	 * twenty seconds by then — the game is the only thing that knows when there
	 * is finally a desktop to look at.
	 */
	public void worldReady() {
		JsonObject o = new JsonObject();
		o.addProperty("t", "world_ready");
		send(o.toString());
	}

	/**
	 * The daemon's last unhandled request to show or hide the overview, or null
	 * if there is none. Reading it consumes it.
	 *
	 * <p>Polled rather than handed to a listener because the socket thread must
	 * not open a Screen — that is render-thread work.
	 */
	public Boolean pollOverviewRequest() {
		return overviewRequest.getAndSet(null);
	}

	/**
	 * The daemon's last unhandled word on whether the game is the focused
	 * window, or null if it has not changed its mind since the last tick.
	 */
	public Boolean pollFocusRequest() {
		return focusRequest.getAndSet(null);
	}

	/** The id of a save the daemon asked for, or null. */
	public Integer pollSaveRequest() {
		return saveRequest.getAndSet(null);
	}

	/** The answer to a save_world. */
	public void worldSaved(int id, boolean ok, long ms) {
		JsonObject o = new JsonObject();
		o.addProperty("t", "world_saved");
		o.addProperty("id", id);
		o.addProperty("ok", ok);
		o.addProperty("ms", ms);
		send(o.toString());
	}

	/**
	 * Queue a message for the daemon. Never blocks; a full queue means the
	 * daemon is not reading, and dropping input events is better than stalling
	 * whichever thread produced them.
	 */
	public void send(String json) {
		if (!outbound.offer(json)) {
			LOG.warn("outbound queue full, dropping: {}", json);
		}
	}

	// -- outbound events ---------------------------------------------------
	// Built with Gson rather than concatenated, so a field that later carries
	// arbitrary text (a command line, a search term) cannot produce a malformed
	// line and drop the connection.

	/**
	 * Confirm that a `focus` has been acted on.
	 *
	 * <p>The daemon holds its focus change until this arrives: the game has to
	 * have let go of the mouse before Sway moves focus off it, or X strands the
	 * grab. See MCShellClient.followWindowFocus.
	 */
	public void focusAck(boolean game) {
		JsonObject o = new JsonObject();
		o.addProperty("t", "focus_ack");
		o.addProperty("game", game);
		send(o.toString());
	}

	/**
	 * Act on a slot. What that means is the daemon's decision, not ours: right
	 * focuses or launches, left cycles that app's windows.
	 *
	 * @param button {@code "left"} or {@code "right"}
	 */
	public void slotActivate(int slot, String button) {
		JsonObject o = new JsonObject();
		o.addProperty("t", "slot_activate");
		o.addProperty("slot", slot);
		o.addProperty("button", button);
		send(o.toString());
	}

	/**
	 * Report the hotbar as the player has just arranged it.
	 *
	 * <p>An observation, not a decision: this says where the application items
	 * now sit, and the daemon decides what that means for its assignments. A
	 * slot the player emptied is simply absent. The answer comes back as an
	 * ordinary {@code taskbar}, so a refusal puts the items back.
	 *
	 * @param slots 0-based hotbar index to desktop id
	 */
	public void slotsArrange(java.util.Map<Integer, String> slots) {
		JsonObject apps = new JsonObject();
		for (Map.Entry<Integer, String> entry : slots.entrySet()) {
			// 1-based on the wire, matching every other slot number in the
			// protocol and the number keys they answer to.
			apps.addProperty(Integer.toString(entry.getKey() + 1), entry.getValue());
		}
		JsonObject o = new JsonObject();
		o.addProperty("t", "slots_arrange");
		o.add("slots", apps);
		send(o.toString());
	}

	/**
	 * Report which hotbar slots hold ordinary Minecraft items.
	 *
	 * <p>The daemon cannot see the player's inventory, and it needs this to
	 * prefer an empty slot when it puts a running application somewhere nobody
	 * assigned. Without it a slot full of wood looks exactly as free as an empty
	 * one, and the wood gets shuffled into storage for nothing.
	 *
	 * @param slots 0-based hotbar indices
	 */
	public void slotsOccupied(java.util.Collection<Integer> slots) {
		JsonArray array = new JsonArray();
		for (Integer slot : new java.util.TreeSet<>(slots)) {
			array.add(slot + 1);
		}
		JsonObject o = new JsonObject();
		o.addProperty("t", "slots_occupied");
		o.add("slots", array);
		send(o.toString());
	}

	/** Politely close one of the slot's windows. */
	public void slotClose(int slot) {
		JsonObject o = new JsonObject();
		o.addProperty("t", "slot_close");
		o.addProperty("slot", slot);
		send(o.toString());
	}

	/**
	 * Ask for the apps matching a tab, a search string, or both.
	 *
	 * <p>The answer arrives later as a {@code catalog} push, into
	 * {@link #catalog()}. There is no request id in the protocol, so a caller
	 * that changes tabs quickly may briefly render the previous answer; replies
	 * arrive in order on one socket, so it settles on the last query asked.
	 *
	 * @param text fuzzy search string, or empty to browse
	 * @param tab  tab to restrict to, or null for every tab
	 */
	public void catalogQuery(String text, String tab) {
		JsonObject o = new JsonObject();
		o.addProperty("t", "catalog_query");
		o.addProperty("text", text == null ? "" : text);
		if (tab != null) {
			o.addProperty("tab", tab);
		}
		send(o.toString());
	}

	/** Put an app in a hotbar slot. The daemon answers with a fresh taskbar. */
	public void slotAssign(int slot, String app) {
		JsonObject o = new JsonObject();
		o.addProperty("t", "slot_assign");
		o.addProperty("slot", slot);
		o.addProperty("app", app);
		send(o.toString());
	}

	/**
	 * Run one line in the command bar.
	 *
	 * <p>What that means is entirely the daemon's business — this is a launcher
	 * and a REPL, and the mod does not know which. The answer comes back as
	 * {@code command_start}, output as it is produced, and {@code command_end}.
	 */
	public void commandSubmit(String text) {
		JsonObject o = new JsonObject();
		o.addProperty("t", "command_submit");
		o.addProperty("text", text);
		send(o.toString());
	}

	/**
	 * Ask for a settings page. The answer arrives as a push, into
	 * {@link #settings(String)}, and further pushes follow whenever the
	 * subsystem behind the page changes underneath us.
	 *
	 * @param page "audio", "video", "controls", or null for every page
	 */
	public void settingsQuery(String page) {
		JsonObject o = new JsonObject();
		o.addProperty("t", "settings_query");
		if (page != null) {
			o.addProperty("page", page);
		}
		send(o.toString());
	}

	/**
	 * Change one setting.
	 *
	 * <p>The value's type has to match what the schema said the row was; the
	 * daemon rejects a mismatch rather than guessing. There is no reply to wait
	 * for — the refreshed page is broadcast, so the screen updates the same way
	 * it would if someone had turned the volume up from anywhere else.
	 */
	public void settingSet(String key, double value) {
		JsonObject o = settingSetBase(key);
		o.addProperty("value", value);
		send(o.toString());
	}

	public void settingSet(String key, boolean value) {
		JsonObject o = settingSetBase(key);
		o.addProperty("value", value);
		send(o.toString());
	}

	public void settingSet(String key, String value) {
		JsonObject o = settingSetBase(key);
		o.addProperty("value", value);
		send(o.toString());
	}

	/**
	 * Bind a key combination, as the keyboard reported it.
	 *
	 * <p>The raw GLFW code and modifier bitmask, and nothing else. Turning
	 * those into a key <em>name</em> is the daemon's job: the mod does not
	 * know what a keysym is, and a table of them over here would be a second
	 * source of truth quietly diverging from the one that matters.
	 */
	public void settingSetKey(String key, int glfwKey, int modifiers) {
		JsonObject value = new JsonObject();
		value.addProperty("glfw", glfwKey);
		value.addProperty("mods", modifiers);
		JsonObject o = settingSetBase(key);
		o.add("value", value);
		send(o.toString());
	}

	private static JsonObject settingSetBase(String key) {
		JsonObject o = new JsonObject();
		o.addProperty("t", "setting_set");
		o.addProperty("key", key);
		return o;
	}

	/** The daemon's next complaint, or null. Consumes it. */
	public String pollError() {
		return errors.poll();
	}

	/** The next thing the daemon said about a command, or null. Consumes it. */
	public CommandEvent pollCommand() {
		return commands.poll();
	}

	/** Empty a hotbar slot. Does not touch the app, only the assignment. */
	public void slotClear(int slot) {
		JsonObject o = new JsonObject();
		o.addProperty("t", "slot_clear");
		o.addProperty("slot", slot);
		send(o.toString());
	}

	// -- connection loop ---------------------------------------------------

	private void run() {
		long backoff = BACKOFF_MIN_MS;

		while (running) {
			try (SocketChannel ch = SocketChannel.open(StandardProtocolFamily.UNIX)) {
				ch.connect(UnixDomainSocketAddress.of(socketPath));
				channel = ch;
				connected = true;
				epoch++;
				backoff = BACKOFF_MIN_MS;
				LOG.info("connected to daemon at {}", socketPath);

				// Anything queued while disconnected refers to a world that no
				// longer exists. Start clean rather than replaying stale clicks.
				outbound.clear();
				send(hello());

				Thread writer = startWriter(ch);
				try {
					readLoop(ch);
				} finally {
					writer.interrupt();
				}
			} catch (IOException e) {
				if (running) {
					LOG.debug("daemon connection failed: {}", e.toString());
				}
			} finally {
				connected = false;
				channel = null;
				state.set(TaskbarState.EMPTY);
				// A stale app list is worse than none: it offers apps to assign
				// while nothing can accept the assignment.
				catalog.set(CatalogState.EMPTY);
				// A request from a connection that is already gone refers to a
				// world that no longer exists; don't pop a screen for it later.
				overviewRequest.set(null);
				// Same for focus: the compositor's answer arrives again on the
				// next hello. Left alone rather than guessed at — releasing the
				// mouse here would drop the player out of a game the daemon's
				// death did nothing to interrupt.
				focusRequest.set(null);
				// A save asked for on a connection that is gone has nobody left
				// waiting for its answer.
				saveRequest.set(null);
				// Whatever a half-finished command had left to say, it will
				// never say now. The bar notices the drop and closes the run
				// off; leaving its tail queued would attach those lines to
				// whatever runs first after the reconnect.
				commands.clear();
				settings.clear();
				// A listing describes a directory as it was; the tree asks again on
				// the next open. Answers to questions asked by a dead connection
				// would attach themselves to whatever is expanded after it.
				dirs.clear();
				errors.clear();
			}

			if (!running) {
				break;
			}
			try {
				Thread.sleep(backoff);
			} catch (InterruptedException e) {
				Thread.currentThread().interrupt();
				break;
			}
			backoff = Math.min(backoff * 2, BACKOFF_MAX_MS);
		}
		LOG.info("daemon connection thread stopped");
	}

	private static String hello() {
		return "{\"t\":\"hello\",\"proto\":" + PROTO + ",\"mc\":\"" + MC_VERSION + "\"}";
	}

	private Thread startWriter(SocketChannel ch) {
		Thread writer = new Thread(() -> {
			OutputStream out = Channels.newOutputStream(ch);
			try {
				while (running && ch.isOpen()) {
					String msg = outbound.poll(200, TimeUnit.MILLISECONDS);
					if (msg == null) {
						continue;
					}
					out.write((msg + "\n").getBytes(StandardCharsets.UTF_8));
					out.flush();
				}
			} catch (InterruptedException e) {
				Thread.currentThread().interrupt();
			} catch (IOException e) {
				LOG.debug("write failed: {}", e.toString());
			}
		}, "mcshell-daemon-write");
		writer.setDaemon(true);
		writer.start();
		return writer;
	}

	private void readLoop(SocketChannel ch) throws IOException {
		BufferedReader reader = new BufferedReader(
				new InputStreamReader(Channels.newInputStream(ch), StandardCharsets.UTF_8));
		String line;
		while (running && (line = reader.readLine()) != null) {
			if (line.isBlank()) {
				continue;
			}
			try {
				handle(line);
			} catch (RuntimeException e) {
				// A malformed message must not take the connection down.
				LOG.warn("bad message from daemon: {}", line, e);
			}
		}
	}

	// -- decoding ----------------------------------------------------------

	private void handle(String line) {
		JsonElement parsed = JsonParser.parseString(line);
		if (!parsed.isJsonObject()) {
			return;
		}
		JsonObject obj = parsed.getAsJsonObject();
		String type = str(obj, "t", "");

		switch (type) {
			case "taskbar" -> state.set(parseTaskbar(obj));
			case "catalog" -> catalog.set(parseCatalog(obj));
			case "overview" -> overviewRequest.set(bool(obj, "show"));
			case "focus" -> focusRequest.set(bool(obj, "game"));
			case "save_world" -> saveRequest.set(num(obj, "id", 0));
			case "command_start" -> commands.add(CommandEvent.start(
					num(obj, "cmd", 0), str(obj, "text", ""), str(obj, "cwd", "")));
			case "output" -> commands.add(CommandEvent.output(
					num(obj, "cmd", 0), strings(obj, "lines"),
					"stderr".equals(str(obj, "stream", "stdout"))));
			// On the command queue rather than a flag of its own, so it is drawn
			// in order: after this run's echo, before its end.
			case "chat_clear" -> commands.add(CommandEvent.clear(num(obj, "cmd", 0)));
			case "command_end" -> commands.add(CommandEvent.end(
					num(obj, "cmd", 0), num(obj, "code", 0), str(obj, "note", "")));
			case "settings_schema" -> storeSettings(obj);
			case "stats" -> storeStats(obj);
			case "worlds" -> worlds.set(parseWorlds(obj));
			case "processes" -> processes.set(parseProcesses(obj));
			case "dir" -> dirs.add(parseDir(obj));
			case "hud" -> hud.set(new HudState(
					bool(obj, "clock"), str(obj, "time", ""), str(obj, "date", ""),
					// Absent means true: this is the only field here whose
					// default is not "off", and a daemon that predates it
					// should leave the gauge doing what it always did.
					!obj.has("battery_color") || bool(obj, "battery_color")));
			case "battery" -> battery.set(new BatteryState(
					bool(obj, "present"), num(obj, "percent", 0),
					bool(obj, "charging"), bool(obj, "mains")));
			case "error" -> {
				String message = str(obj, "message", "?");
				LOG.warn("daemon error: {}", message);
				errors.add(message);
				while (errors.size() > 8) {
					errors.poll();
				}
			}
			case "ok", "pong" -> { /* nothing to do */ }
			default -> LOG.debug("ignoring message type {}", type);
		}
	}

	private static WorldsState parseWorlds(JsonObject obj) {
		List<WorldsState.World> list = new ArrayList<>();
		if (obj.has("worlds") && obj.get("worlds").isJsonArray()) {
			for (JsonElement element : obj.getAsJsonArray("worlds")) {
				if (element.isJsonObject()) {
					JsonObject o = element.getAsJsonObject();
					list.add(new WorldsState.World(
							str(o, "name", ""), str(o, "icon", ""), num(o, "icon_version", 0)));
				}
			}
		}
		return new WorldsState(List.copyOf(list), str(obj, "chosen", ""), str(obj, "running", ""));
	}

	private void storeStats(JsonObject obj) {
		String tab = str(obj, "tab", "general");
		List<StatsState.Row> rows = new ArrayList<>();
		if (obj.has("rows") && obj.get("rows").isJsonArray()) {
			for (JsonElement element : obj.getAsJsonArray("rows")) {
				if (!element.isJsonObject()) {
					continue;
				}
				JsonObject o = element.getAsJsonObject();
				JsonElement fraction = o.get("fraction");
				rows.add(new StatsState.Row(
						str(o, "group", ""), str(o, "label", ""), str(o, "value", ""),
						str(o, "detail", ""),
						fraction == null || fraction.isJsonNull()
								? -1.0F : fraction.getAsFloat()));
			}
		}
		stats.put(tab, new StatsState(tab, List.copyOf(rows)));
	}

	private static ProcessState parseProcesses(JsonObject obj) {
		List<ProcessState.Row> procs = new ArrayList<>();
		if (obj.has("procs") && obj.get("procs").isJsonArray()) {
			for (JsonElement element : obj.getAsJsonArray("procs")) {
				if (!element.isJsonObject()) {
					continue;
				}
				JsonObject o = element.getAsJsonObject();
				procs.add(new ProcessState.Row(
						num(o, "pid", 0), str(o, "name", ""), str(o, "cmd", ""),
						str(o, "user", ""), (float) dbl(o, "cpu"), (float) dbl(o, "mem"),
						(long) dbl(o, "rss"), bool(o, "protected")));
			}
		}
		return new ProcessState(
				(float) dbl(obj, "cpu"), floats(obj, "cores"),
				(long) dbl(obj, "mem_used"), (long) dbl(obj, "mem_total"),
				(long) dbl(obj, "swap_used"), (long) dbl(obj, "swap_total"),
				floats(obj, "load"), num(obj, "count", 0), List.copyOf(procs));
	}

	private static List<Float> floats(JsonObject o, String key) {
		List<Float> out = new ArrayList<>();
		if (o.has(key) && o.get(key).isJsonArray()) {
			for (JsonElement element : o.getAsJsonArray(key)) {
				out.add(element.isJsonNull() ? 0.0F : element.getAsFloat());
			}
		}
		return List.copyOf(out);
	}

	private static double dbl(JsonObject o, String key) {
		JsonElement e = o.get(key);
		return e == null || e.isJsonNull() ? 0.0 : e.getAsDouble();
	}

	private static DirState parseDir(JsonObject obj) {
		List<DirState.Entry> entries = new ArrayList<>();
		if (obj.has("entries") && obj.get("entries").isJsonArray()) {
			for (JsonElement element : obj.getAsJsonArray("entries")) {
				if (!element.isJsonObject()) {
					continue;
				}
				JsonObject o = element.getAsJsonObject();
				entries.add(new DirState.Entry(
						str(o, "name", ""), str(o, "path", ""), str(o, "kind", "file")));
			}
		}
		return new DirState(str(obj, "path", ""), str(obj, "name", ""), List.copyOf(entries),
				num(obj, "total", 0), num(obj, "hidden", 0), num(obj, "offset", 0),
				str(obj, "error", ""));
	}

	/** The next directory listing to arrive, or null. Drained by the file tree. */
	public DirState nextDir() {
		return dirs.poll();
	}

	/**
	 * Ask for one directory's subdirectories.
	 *
	 * <p>An empty path means the home directory. The answer holds its
	 * subdirectories and its files, in that order. Nothing is cached on either
	 * side: a directory read is a syscall, and the answer stops being true the
	 * moment somebody saves a file.
	 */
	public void dirQuery(String path, int offset, int limit) {
		JsonObject o = new JsonObject();
		o.addProperty("t", "dir_query");
		o.addProperty("path", path);
		o.addProperty("offset", offset);
		o.addProperty("limit", limit);
		send(o.toString());
	}

	public void worldsQuery() {
		JsonObject o = new JsonObject();
		o.addProperty("t", "worlds_query");
		send(o.toString());
	}

	public void worldChoose(String name) {
		JsonObject o = new JsonObject();
		o.addProperty("t", "world_choose");
		o.addProperty("name", name);
		send(o.toString());
	}

	public void worldRestart() {
		JsonObject o = new JsonObject();
		o.addProperty("t", "world_restart");
		send(o.toString());
	}

	public void statsQuery(String tab) {
		JsonObject o = new JsonObject();
		o.addProperty("t", "stats_query");
		o.addProperty("tab", tab);
		send(o.toString());
	}

	/**
	 * Ask for, or stop, the live process stream.
	 *
	 * <p>Sent on opening and closing the task-manager tab, and again whenever
	 * a column header is clicked: the order is the daemon's to apply.
	 */
	public void statsWatch(boolean on, String sort, boolean desc, int limit) {
		JsonObject o = new JsonObject();
		o.addProperty("t", "stats_watch");
		o.addProperty("on", on);
		o.addProperty("sort", sort);
		o.addProperty("desc", desc);
		o.addProperty("limit", limit);
		send(o.toString());
	}

	/**
	 * Lock, sleep, restart or power off the machine.
	 *
	 * <p>A request, like {@code slot_close} and the kill button. The daemon
	 * answers as soon as it has accepted it, not when it has finished, so
	 * nothing here waits — a failure arrives afterwards as an error and the
	 * screen shows it like any other.
	 */
	public void powerAction(String action) {
		JsonObject o = new JsonObject();
		o.addProperty("t", "power_action");
		o.addProperty("action", action);
		send(o.toString());
	}

	public void processKill(int pid) {
		JsonObject o = new JsonObject();
		o.addProperty("t", "process_kill");
		o.addProperty("pid", pid);
		send(o.toString());
	}

	private static CatalogState parseCatalog(JsonObject obj) {
		List<CatalogState.Item> items = new ArrayList<>();
		if (obj.has("items") && obj.get("items").isJsonArray()) {
			for (JsonElement element : obj.getAsJsonArray("items")) {
				if (!element.isJsonObject()) {
					continue;
				}
				JsonObject o = element.getAsJsonObject();
				items.add(new CatalogState.Item(
						str(o, "id", ""),
						str(o, "name", ""),
						str(o, "icon_path", null),
						str(o, "tab", "")));
			}
		}
		return new CatalogState(List.copyOf(items));
	}

	/**
	 * File a schema under the page it describes.
	 *
	 * <p>A schema for every page at once (what `settings_query` with no page
	 * asks for) is split up by each row's own page, so the pages stay
	 * independently replaceable however they were fetched.
	 */
	private void storeSettings(JsonObject obj) {
		String page = str(obj, "page", "");
		List<SettingsState.Row> rows = parseSettings(obj);
		if (!page.isEmpty()) {
			settings.put(page, new SettingsState(page, rows));
			return;
		}
		Map<String, List<SettingsState.Row>> byPage = new java.util.LinkedHashMap<>();
		for (SettingsState.Row row : rows) {
			byPage.computeIfAbsent(rowPage(row), k -> new ArrayList<>()).add(row);
		}
		byPage.forEach((name, list) ->
				settings.put(name, new SettingsState(name, List.copyOf(list))));
	}

	/** A row's page, taken from its key, which is namespaced by page name. */
	private static String rowPage(SettingsState.Row row) {
		int dot = row.key().indexOf('.');
		return dot < 0 ? "" : row.key().substring(0, dot);
	}

	private static List<SettingsState.Row> parseSettings(JsonObject obj) {
		List<SettingsState.Row> rows = new ArrayList<>();
		if (!obj.has("items") || !obj.get("items").isJsonArray()) {
			return List.of();
		}
		for (JsonElement element : obj.getAsJsonArray("items")) {
			if (!element.isJsonObject()) {
				continue;
			}
			JsonObject o = element.getAsJsonObject();
			JsonElement value = o.get("value");
			boolean hasValue = value != null && value.isJsonPrimitive();
			List<SettingsState.Option> options = new ArrayList<>();
			if (o.has("options") && o.get("options").isJsonArray()) {
				for (JsonElement opt : o.getAsJsonArray("options")) {
					if (opt.isJsonObject()) {
						JsonObject p = opt.getAsJsonObject();
						options.add(new SettingsState.Option(
								str(p, "id", ""), str(p, "label", "")));
					}
				}
			}
			rows.add(new SettingsState.Row(
					str(o, "key", ""),
					SettingsState.Type.of(str(o, "type", "label")),
					str(o, "label", ""),
					str(o, "group", ""),
					str(o, "detail", ""),
					hasValue && value.getAsJsonPrimitive().isNumber() ? value.getAsDouble() : 0.0,
					hasValue && value.getAsJsonPrimitive().isBoolean() && value.getAsBoolean(),
					hasValue && value.getAsJsonPrimitive().isString() ? value.getAsString() : null,
					str(o, "default", null),
					dbl(o, "min", 0.0),
					dbl(o, "max", 1.0),
					dbl(o, "step", 0.0),
					str(o, "unit", ""),
					List.copyOf(options),
					!o.has("enabled") || bool(o, "enabled"),
					str(o, "placeholder", ""),
					str(o, "extra_label", ""),
					str(o, "extra_key", "")));
		}
		return List.copyOf(rows);
	}

	private static double dbl(JsonObject o, String key, double fallback) {
		JsonElement e = o.get(key);
		return e == null || e.isJsonNull() ? fallback : e.getAsDouble();
	}

	private static TaskbarState parseTaskbar(JsonObject obj) {
		List<TaskbarState.Slot> slots = new ArrayList<>();
		if (obj.has("slots") && obj.get("slots").isJsonArray()) {
			for (JsonElement element : obj.getAsJsonArray("slots")) {
				if (!element.isJsonObject()) {
					continue;
				}
				JsonObject s = element.getAsJsonObject();
				slots.add(new TaskbarState.Slot(
						num(s, "i", 0),
						str(s, "app", null),
						str(s, "name", null),
						str(s, "icon_path", null),
						bool(s, "running"),
						num(s, "windows", 0),
						bool(s, "focused"),
						bool(s, "launching")));
			}
		}
		return new TaskbarState(List.copyOf(slots));
	}

	private static List<String> strings(JsonObject o, String key) {
		List<String> out = new ArrayList<>();
		if (o.has(key) && o.get(key).isJsonArray()) {
			for (JsonElement element : o.getAsJsonArray(key)) {
				if (element.isJsonPrimitive()) {
					out.add(element.getAsString());
				}
			}
		}
		return out;
	}

	private static String str(JsonObject o, String key, String fallback) {
		JsonElement e = o.get(key);
		return e == null || e.isJsonNull() ? fallback : e.getAsString();
	}

	private static int num(JsonObject o, String key, int fallback) {
		JsonElement e = o.get(key);
		return e == null || e.isJsonNull() ? fallback : e.getAsInt();
	}

	private static boolean bool(JsonObject o, String key) {
		JsonElement e = o.get(key);
		return e != null && !e.isJsonNull() && e.getAsBoolean();
	}

	private void closeQuietly() {
		SocketChannel ch = channel;
		if (ch != null) {
			try {
				ch.close();
			} catch (IOException ignored) {
				// closing is best effort
			}
		}
	}
}
