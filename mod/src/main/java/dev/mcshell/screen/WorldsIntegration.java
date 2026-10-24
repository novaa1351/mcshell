package dev.mcshell.screen;

import dev.mcshell.net.DaemonConnection;
import net.minecraft.client.MinecraftClient;
import net.minecraft.client.gui.screen.Screen;

/**
 * Where the pause menu's <i>Give Feedback</i> button goes: the world picker.
 *
 * <p>A holder rather than a screen event, like {@link PowerIntegration},
 * because what is replaced is a button inside a static layout method, which a
 * mixin can reach and a screen event cannot.
 */
public final class WorldsIntegration {
	private WorldsIntegration() {
	}

	private static DaemonConnection connection;

	public static void register(DaemonConnection daemon) {
		connection = daemon;
	}

	/** Whether there is a shell to answer. Without one, vanilla's link stays. */
	public static boolean available() {
		return connection != null;
	}

	public static void open(Screen parent) {
		MinecraftClient client = MinecraftClient.getInstance();
		if (connection != null && client != null) {
			client.setScreen(new WorldsScreen(connection, parent));
		}
	}
}
