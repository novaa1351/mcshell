package dev.mcshell;

import dev.mcshell.command.CommandBar;
import dev.mcshell.command.CommandLog;
import dev.mcshell.item.AppGestures;
import dev.mcshell.item.AppInventory;
import dev.mcshell.item.AppItems;
import dev.mcshell.net.DaemonConnection;
import dev.mcshell.render.IconTextures;
import dev.mcshell.screen.AdvancementsIntegration;
import dev.mcshell.screen.InventoryIntegration;
import dev.mcshell.screen.OverviewScreen;
import dev.mcshell.screen.PowerIntegration;
import dev.mcshell.screen.WorldsIntegration;
import dev.mcshell.screen.SettingsIntegration;
import dev.mcshell.screen.StatsIntegration;
import net.fabricmc.api.ClientModInitializer;
import net.fabricmc.fabric.api.client.event.lifecycle.v1.ClientLifecycleEvents;
import net.fabricmc.fabric.api.client.event.lifecycle.v1.ClientTickEvents;
import net.fabricmc.fabric.api.client.keybinding.v1.KeyBindingHelper;
import net.minecraft.client.MinecraftClient;
import net.minecraft.server.integrated.IntegratedServer;
import java.util.function.Supplier;
import net.minecraft.client.gui.screen.DownloadingTerrainScreen;
import net.minecraft.client.gui.screen.world.LevelLoadingScreen;
import net.minecraft.client.option.KeyBinding;
import net.minecraft.client.util.InputUtil;
import org.lwjgl.glfw.GLFW;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

/**
 * Client entrypoint.
 *
 * <p>The mod is deliberately dumb: it renders daemon state and forwards input
 * events. Anything resembling a decision — what an app is, whether it is
 * running, what a click should do — belongs in the daemon.
 */
public class MCShellClient implements ClientModInitializer {
	public static final String MOD_ID = "mcshell";
	public static final Logger LOG = LoggerFactory.getLogger(MOD_ID);

	private static DaemonConnection connection;
	/** One cache for the whole mod: the hotbar and the overview draw the same icons. */
	private static IconTextures icons;
	private static KeyBinding overviewKey;
	/** The command bar's transcript. Client-thread only; the panel draws it. */
	private static CommandLog log;
	private static CommandBar commandBar;
	/** Keeps the real hotbar holding what the daemon says is there. */
	private static AppInventory appInventory;

	@Override
	public void onInitializeClient() {
		// Before anything can draw a stack. Registries are still open here —
		// fabric-api removes the freeze from Bootstrap's path — and the item
		// has to exist before the first resource load looks for its model.
		AppItems.register();

		connection = new DaemonConnection(DaemonConnection.defaultSocketPath());
		connection.start();
		icons = new IconTextures();

		// Backtick: unbound in vanilla, and rebindable from Options > Controls
		// like any other key. Super is not available — it belongs to Sway, which
		// raises Minecraft with it and then asks the daemon to push an overview.
		overviewKey = KeyBindingHelper.registerKeyBinding(new KeyBinding(
				"key.mcshell.overview", InputUtil.Type.KEYSYM,
				GLFW.GLFW_KEY_GRAVE_ACCENT, "key.categories.mcshell"));

		// Chat is the command bar. Every plain line is a command; Minecraft's
		// own slash commands are left alone.
		log = new CommandLog();
		commandBar = new CommandBar(connection, log);
		commandBar.register();

		// E stays the survival inventory. The catalog hangs off a chest button
		// on it, so the survival flavour survives having a desktop in it.
		InventoryIntegration.register(connection);

		// Minecraft's own options screens grow a bottom-left button that
		// crosses to the machine's settings. Its sliders keep controlling
		// Minecraft; these control the box it is running on.
		SettingsIntegration.register(connection);

		// The pause menu's Statistics button, pointed at the machine.
		StatsIntegration.register(connection);
		AdvancementsIntegration.register(connection);

		// Save and Quit to Title, pointed at the machine's power state. There
		// is no title screen to go back to in a shell.
		PowerIntegration.register(connection);

		// Give Feedback, pointed at the world picker.
		WorldsIntegration.register(connection);

		// The hotbar's applications are real items now, kept in step with the
		// taskbar. One way: the daemon still decides, this only writes it down.
		appInventory = new AppInventory(connection);

		ClientTickEvents.END_CLIENT_TICK.register(MCShellClient::tick);
		ClientLifecycleEvents.CLIENT_STOPPING.register(client -> connection.stop());

		LOG.info("mcshell client ready; daemon socket {}", DaemonConnection.defaultSocketPath());
	}

	private static void tick(MinecraftClient client) {
		commandBar.tick();
		appInventory.tick(client);
		AppGestures.tick(client);
		followWindowFocus(client);
		reportWorldReady(client);
		answerSaveRequest(client);

		Boolean request = connection.pollOverviewRequest();
		if (request != null) {
			setOverview(client, request);
		}

		// A loop, not an if: the binding counts presses, and leaving extras on
		// the counter would toggle the overview again on the next tick.
		while (overviewKey.wasPressed()) {
			setOverview(client, !(client.currentScreen instanceof OverviewScreen));
		}
	}

	/**
	 * Save the world because the daemon asked, and say when it is on disk.
	 *
	 * <p>The daemon asks before the machine powers off or restarts, holding
	 * logind back while it waits. Nothing else can save it at that point: the
	 * compositor goes first at shutdown and this client dies with its display.
	 *
	 * <p>Exactly what vanilla's {@code /save-all flush} runs —
	 * {@code saveAll(false, true, true)}, player data and then every chunk,
	 * flushed — read out of {@code SaveAllCommand} rather than approximated.
	 * On the server thread, because that is the thread that owns the world;
	 * the answer is sent from there when the save completes.
	 *
	 * <p>No decision is made here. Whether and when to save is the daemon's.
	 */
	private static void answerSaveRequest(MinecraftClient client) {
		Integer id = connection.pollSaveRequest();
		if (id == null) {
			return;
		}
		IntegratedServer server = client.getServer();
		if (server == null) {
			connection.worldSaved(id, false, 0);
			return;
		}
		long started = System.nanoTime();
		Supplier<Boolean> save = () -> server.saveAll(false, true, true);
		server.submit(save).whenComplete((saved, error) -> {
			long ms = (System.nanoTime() - started) / 1_000_000;
			if (error == null) {
				LOG.info("saved the world for the daemon in {}ms", ms);
			} else {
				LOG.warn("could not save the world for the daemon", error);
			}
			connection.worldSaved(id, error == null, ms);
		});
	}

	/** The connection the last {@code world_ready} was sent on, or -1. */
	private static long worldReadyEpoch = -1;

	/**
	 * Tell the daemon when the world is actually on screen.
	 *
	 * <p>The daemon draws a boot screen over the whole output from the moment
	 * it starts — sway's flat colour, Prism's launcher and Minecraft's own
	 * Mojang splash are three unrelated pictures and this replaces all of them.
	 * Everything it draws until this message is an estimate against how long
	 * the last boot took; this is the one thing that ends it, which is why the
	 * percentage is capped at 99 until it arrives.
	 *
	 * <p>Once per <em>connection</em>, not once per run. A daemon restarted
	 * with {@code $mod+Shift+d} starts a fresh boot screen, and if nothing told
	 * it the world was already up it would cover a working desktop until its
	 * timeout. The daemon has its own guard for that — it sees Minecraft's
	 * window already mapped — and this is the other half of the same door.
	 *
	 * <p>Not sent while an overlay or a loading screen is up. {@code world !=
	 * null} goes true well before there is anything to look at: the Mojang
	 * splash is an {@code Overlay} drawn over a world that already exists.
	 */
	private static void reportWorldReady(MinecraftClient client) {
		if (!connection.connected() || connection.epoch() == worldReadyEpoch) {
			return;
		}
		if (client.world == null || client.player == null) {
			return;
		}
		if (client.getOverlay() != null
				|| client.currentScreen instanceof LevelLoadingScreen
				|| client.currentScreen instanceof DownloadingTerrainScreen) {
			return;
		}
		worldReadyEpoch = connection.epoch();
		connection.worldReady();
		LOG.info("world is up; told the daemon to take the boot screen down");
	}

	/** Whether the game had the compositor's focus last tick, as GLFW sees it. */
	private static boolean windowFocused = true;

	/**
	 * Let go of the mouse whenever the shell is looking at something else.
	 *
	 * <p>Vanilla releases the cursor by pausing when the window loses focus,
	 * and the shell turns pausing off — a backdrop that opens the pause menu
	 * behind every window you use is not a backdrop. But that release was doing
	 * real work, and dropping it cost more than it looked like.
	 *
	 * <p>Minecraft runs under XWayland, and a client that holds the pointer
	 * there holds it for the whole X server. So the game kept the cursor
	 * captured while an application was on top: the camera turned under the
	 * window you were working in, and every other XWayland application — a
	 * document editor, say — stopped receiving button presses while still
	 * receiving pointer motion, which reads as a window you can type into and
	 * cannot click.
	 *
	 * <p>Asking GLFW is not enough, and this is the part that took three tries.
	 * GLFW only reports a lost focus when another <em>X</em> client takes it,
	 * so focusing a native Wayland window — a file manager, a terminal, most of
	 * the desktop — left the game believing it was still focused and still
	 * holding the mouse. Measured, not reasoned: focusing an XWayland editor
	 * reported {@code focused=false}; focusing kitty reported
	 * {@code focused=true} while the camera went on turning underneath it.
	 *
	 * <p>So the compositor answers instead, through the daemon, which is
	 * watching Sway for the taskbar anyway. The GLFW path stays as the fallback
	 * for a daemon that is not running; the two only both fire on the X-to-X
	 * case, and they agree there.
	 *
	 * <p>The acknowledgement is not a courtesy. GLFW hands an X grab back only
	 * while X still says the game is focused, so this has to happen <em>before</em>
	 * Sway moves focus, and the daemon waits on the reply to make that true.
	 * Daemon.yield_pointer has the measurement. Releasing afterwards instead
	 * strands the grab: the camera stops, which looks like a fix, and every
	 * other X client goes on losing its clicks to a window ignoring them.
	 */
	private static void followWindowFocus(MinecraftClient client) {
		Boolean fromShell = connection.pollFocusRequest();
		if (fromShell != null) {
			setCursorHeld(client, fromShell);
			// The daemon is holding its focus change until this goes back.
			connection.focusAck(fromShell);
		}

		boolean focused = client.isWindowFocused();
		if (focused != windowFocused) {
			windowFocused = focused;
			setCursorHeld(client, focused);
		}
	}

	/**
	 * Hold or release the mouse. Idempotent, because two sources ask for it.
	 *
	 * <p>Re-taking it uses vanilla's own rule — only with no screen open — so
	 * raising the game while the overview is up does not grab the pointer out
	 * from under the panel the player is reading.
	 */
	private static void setCursorHeld(MinecraftClient client, boolean held) {
		if (client.mouse == null) {
			return;
		}
		if (!held) {
			if (client.mouse.isCursorLocked()) {
				client.mouse.unlockCursor();
			}
		} else if (client.currentScreen == null && !client.mouse.isCursorLocked()) {
			client.mouse.lockCursor();
		}
	}

	private static void setOverview(MinecraftClient client, boolean show) {
		boolean open = client.currentScreen instanceof OverviewScreen;
		if (show == open) {
			return;
		}
		if (!show) {
			client.setScreen(null);
			return;
		}
		// There is nothing to overlay on the title screen, and closing the
		// overview from there would leave the client with no screen at all.
		if (client.world == null) {
			return;
		}
		client.setScreen(new OverviewScreen(connection, log));
	}

	/**
	 * Open the overview because output outgrew chat.
	 *
	 * <p>Only over the world or over the overview itself. A command submitted
	 * from `mcsh` can finish at any moment, and taking the screen away from
	 * someone using the catalog — mid-carry, even — is not worth showing them
	 * output they did not ask for here.
	 */
	public static void showOverview() {
		MinecraftClient client = MinecraftClient.getInstance();
		if (client.currentScreen == null || client.currentScreen instanceof OverviewScreen) {
			setOverview(client, true);
		}
	}

	public static DaemonConnection connection() {
		return connection;
	}

	/**
	 * The shared icon cache, or null before the client has initialised.
	 *
	 * <p>Nullable because the item renderer can be reached from anywhere, and a
	 * missing cache means the placeholder tile rather than a crash.
	 */
	public static IconTextures icons() {
		return icons;
	}

	/** Bound key for the overview, so the screen can recognise its own close key. */
	public static KeyBinding overviewKey() {
		return overviewKey;
	}
}
