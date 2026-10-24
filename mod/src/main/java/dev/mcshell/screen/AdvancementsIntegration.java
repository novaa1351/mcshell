package dev.mcshell.screen;

import dev.mcshell.mixin.AdvancementsScreenAccessor;
import dev.mcshell.net.DaemonConnection;
import net.fabricmc.fabric.api.client.screen.v1.ScreenEvents;
import net.minecraft.client.gui.screen.Screen;
import net.minecraft.client.gui.screen.advancement.AdvancementsScreen;

/**
 * Sends the Advancements screen to the filesystem.
 *
 * <p>Buried rather than moved aside, the way Open to LAN and Statistics are:
 * there is no button back and no way to reach vanilla's. In a superflat void
 * with mob spawning off, the advancement tree is a screen of things that will
 * never happen — and it is the one vanilla window already built to draw a
 * tree, which is what a directory is.
 *
 * <p>Redirected after init for the same reason as the others: the screen being
 * replaced has finished building, so nothing is half-constructed when it goes
 * away, and {@code setScreen} calls its {@code removed()}, which is what drops
 * vanilla's advancement listener.
 */
public final class AdvancementsIntegration {
	private AdvancementsIntegration() {
	}

	public static void register(DaemonConnection connection) {
		ScreenEvents.AFTER_INIT.register((client, screen, width, height) -> {
			if (screen instanceof AdvancementsScreen) {
				Screen parent = ((AdvancementsScreenAccessor) screen).mcshell$parent();
				client.setScreen(new FileTreeScreen(connection, parent));
			}
		});
	}
}
