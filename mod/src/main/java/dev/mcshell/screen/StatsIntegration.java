package dev.mcshell.screen;

import dev.mcshell.net.DaemonConnection;
import net.fabricmc.fabric.api.client.screen.v1.ScreenEvents;
import dev.mcshell.mixin.StatsScreenAccessor;
import net.minecraft.client.gui.screen.Screen;
import net.minecraft.client.gui.screen.StatsScreen;

/**
 * Sends the pause menu's Statistics button to the machine's statistics.
 *
 * <p>Vanilla's screen is buried rather than moved aside, the way Open to LAN
 * is: there is no button back and no way to reach it. Minecraft's own
 * statistics are blocks mined and mobs killed, and in a superflat void with
 * mob spawning off and random ticks at zero they are three screens of zeroes.
 *
 * <p>The pause-menu button keeps saying <i>Statistics</i>, which needs no
 * argument — it is statistics, about the thing the shell is a shell for.
 *
 * <p>Redirected after init rather than before it, for the same reason the
 * settings lanes are: the screen we replace has finished building, so nothing
 * is half-constructed when it goes away. Vanilla's own {@code init} has by
 * then asked the server for stats, which in singleplayer is a packet to
 * ourselves and costs nothing.
 */
public final class StatsIntegration {
	private StatsIntegration() {
	}

	public static void register(DaemonConnection connection) {
		ScreenEvents.AFTER_INIT.register((client, screen, width, height) -> {
			if (screen instanceof StatsScreen) {
				// Its parent, not itself. Handing this screen the one it is
				// replacing makes closing a loop — the vanilla screen is
				// redirected on init, so it would bounce straight back and
				// there would be no way out at all.
				Screen parent = ((StatsScreenAccessor) screen).mcshell$parent();
				client.setScreen(new MachineStatsScreen(connection, parent));
			}
		});
	}
}
