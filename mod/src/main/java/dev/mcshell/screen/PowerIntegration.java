package dev.mcshell.screen;

import dev.mcshell.net.DaemonConnection;
import net.minecraft.client.MinecraftClient;
import net.minecraft.client.gui.screen.Screen;

/**
 * Where the pause menu's last button goes.
 *
 * <p>A plain class rather than a screen event, because the thing being
 * replaced is a button's action and not a screen. The mixin on
 * {@code GameMenuScreen} calls in here; this holds the one thing a mixin
 * cannot be handed at construction — the daemon connection.
 */
public final class PowerIntegration {
	private PowerIntegration() {
	}

	private static DaemonConnection connection;

	public static void register(DaemonConnection daemon) {
		connection = daemon;
	}

	/**
	 * Show the power menu, if there is a shell behind it.
	 *
	 * @return whether it opened — false leaves vanilla's own behaviour alone
	 */
	public static boolean open(Screen parent) {
		MinecraftClient client = MinecraftClient.getInstance();
		if (connection == null || client == null) {
			return false;
		}
		client.setScreen(new PowerScreen(connection, parent));
		return true;
	}
}
