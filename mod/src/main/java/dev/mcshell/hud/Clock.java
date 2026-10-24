package dev.mcshell.hud;

import dev.mcshell.MCShellClient;
import dev.mcshell.net.DaemonConnection;
import dev.mcshell.net.HudState;
import net.minecraft.client.MinecraftClient;
import net.minecraft.client.font.TextRenderer;
import net.minecraft.client.gui.DrawContext;

/**
 * The local date and time, along the top of the screen.
 *
 * <p>The shell had nowhere at all that said what time it is. Minecraft's own
 * clock is an item that reads the world's daylight cycle, and this world has
 * neither daylight nor a cycle — so a desktop made of Minecraft was a desktop
 * you had to open an application to check the time on.
 *
 * <p><b>The string is the daemon's; only the pixels are ours.</b> "Read the
 * system locale" means glibc's locale, which is what {@code strftime} answers
 * for; the JVM has its own idea of a default locale, taken from the same
 * environment but mapped through its own tables, and the two disagree often
 * enough to matter. So {@code clock.py} formats and this prints. It also means
 * the clock is pushed on the minute rather than read every frame, which is
 * sixty times less work than asking a system call what time it is.
 *
 * <p>Top left, at the margin vanilla uses for the chat and the debug overlay,
 * and drawn the way vanilla draws HUD text: one string, one drop shadow. The
 * time is yellow and the date white, which is the one thing here that is a
 * choice rather than a copy — the two are read for different reasons and at a
 * glance the time should be the part your eye lands on.
 *
 * <p>There is no sun or moon beside it. The reference this was built from
 * shows one, because that mod is displaying the <em>world's</em> time as well;
 * this world has {@code doDaylightCycle false} and a void sky, so an icon for
 * the time of day would be an icon that never changed.
 *
 * <p>Hidden under F1 and behind F3, like everything else in this corner.
 */
public final class Clock {
	private Clock() {
	}

	/** Vanilla's chat and debug-overlay margin. */
	private static final int X = 4;
	private static final int Y = 4;

	/** Vanilla's {@code Formatting.YELLOW}, and plain white. */
	private static final int TIME_COLOR = 0xFFFF55;
	private static final int DATE_COLOR = 0xFFFFFF;

	/** An en dash with spaces around it, as in the reference. */
	private static final String SEPARATOR = " – ";

	public static void draw(DrawContext context) {
		MinecraftClient client = MinecraftClient.getInstance();
		if (client == null || client.options.hudHidden) {
			return;
		}
		// F3 draws in this corner too, and it is the more urgent of the two.
		if (client.getDebugHud().shouldShowDebugHud()) {
			return;
		}
		DaemonConnection connection = MCShellClient.connection();
		if (connection == null) {
			return;
		}
		HudState hud = connection.hud();
		if (!hud.showClock()) {
			return;
		}

		TextRenderer text = client.textRenderer;
		context.drawTextWithShadow(text, hud.time(), X, Y, TIME_COLOR);
		int x = X + text.getWidth(hud.time());
		if (!hud.date().isEmpty()) {
			context.drawTextWithShadow(text, SEPARATOR + hud.date(), x, Y, DATE_COLOR);
		}
	}
}
