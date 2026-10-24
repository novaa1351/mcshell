package dev.mcshell.hud;

import com.mojang.blaze3d.systems.RenderSystem;
import dev.mcshell.MCShellClient;
import dev.mcshell.net.BatteryState;
import dev.mcshell.net.DaemonConnection;
import net.minecraft.client.MinecraftClient;
import net.minecraft.client.font.TextRenderer;
import net.minecraft.client.gui.DrawContext;
import net.minecraft.util.Identifier;

/**
 * The XP bar, drawn as the battery.
 *
 * <p>The shell has nowhere else to put a charge gauge, and a laptop you have to
 * guess about is a bad laptop. So the bar fills with charge rather than
 * experience and the level reads {@code 80%} rather than {@code 80}.
 *
 * <p><b>Minecraft's experience is untouched.</b> Orbs are still picked up and
 * levels still accrue — enchanting still works, and the numbers are still there
 * in the screens that are about them. What changes is that the HUD stops
 * drawing them, so picking up experience cannot move the battery gauge and the
 * two systems can never disagree on screen. That is the whole reason this is a
 * drawing change and not a change to the player: a gauge that had to fight the
 * game for the same five pixels would lose one day.
 *
 * <p>Vanilla's geometry, copied out of {@code InGameHud} rather than
 * approximated — the same sprites, the same 182x5 at
 * {@code height - 32 + 3}, the same four-offset black outline on the number.
 * A battery gauge that was nearly the XP bar would read as a mod; this one is
 * the XP bar.
 *
 * <p>Colour can be switched off on the General page, which pins the bar green.
 * The three colours are real information — white on mains, red below 15% — but
 * a gauge that changes colour under you is a thing somebody is allowed to not
 * want, and it is the only part of this that is ours rather than vanilla's.
 *
 * <p>The one departure is the fill. Vanilla scales progress by 183 into a
 * 182-wide sprite, which only shows at a full bar — and vanilla never has one,
 * because levelling resets progress to zero. A battery sits at 100% for hours,
 * so this rounds into 0..182 and the last pixel is not stretched.
 */
public final class BatteryBar {
	private BatteryBar() {
	}

	private static final Identifier BACKGROUND =
			Identifier.ofVanilla("hud/experience_bar_background");
	private static final Identifier PROGRESS =
			Identifier.ofVanilla("hud/experience_bar_progress");

	private static final int BAR_W = 182;
	private static final int BAR_H = 5;

	/** Vanilla's own experience green, the literal from {@code InGameHud}. */
	private static final int GREEN = 8453920;
	private static final int WHITE = 0xFFFFFF;
	/** Vanilla's {@code Formatting.RED}. */
	private static final int RED = 0xFF5555;
	/** Below this, and running on the battery, the number turns red. */
	private static final int LOW = 15;

	/**
	 * Draw the battery bar, or say no and let Minecraft draw its own.
	 *
	 * @return true when this drew, and vanilla's should be cancelled
	 */
	public static boolean drawBar(DrawContext context, int x) {
		BatteryState battery = state();
		if (battery == null || !battery.present()) {
			return false;
		}
		int y = context.getScaledWindowHeight() - 32 + 3;
		int filled = Math.round(battery.fraction() * BAR_W);

		RenderSystem.enableBlend();
		context.drawGuiTexture(BACKGROUND, x, y, BAR_W, BAR_H);
		if (filled > 0) {
			context.drawGuiTexture(PROGRESS, BAR_W, BAR_H, 0, 0, x, y, filled, BAR_H);
		}
		RenderSystem.disableBlend();
		return true;
	}

	/** The percentage where the level number goes. Same contract as above. */
	public static boolean drawLevel(DrawContext context) {
		BatteryState battery = state();
		if (battery == null || !battery.present()) {
			return false;
		}
		MinecraftClient client = MinecraftClient.getInstance();
		if (client == null) {
			return false;
		}
		TextRenderer text = client.textRenderer;

		String label = battery.percent() + "%";
		int x = (context.getScaledWindowWidth() - text.getWidth(label)) / 2;
		int y = context.getScaledWindowHeight() - 31 - 4;

		// Vanilla's outline: the same string in black at four offsets, then the
		// real one over it. Not a shadow — drawText's own shadow sits bottom
		// right only, and the XP number has never used it.
		context.drawText(text, label, x + 1, y, 0, false);
		context.drawText(text, label, x - 1, y, 0, false);
		context.drawText(text, label, x, y + 1, 0, false);
		context.drawText(text, label, x, y - 1, 0, false);
		context.drawText(text, label, x, y, colorFor(battery), false);
		return true;
	}

	/**
	 * Green on the battery, white on mains, red when low and unplugged.
	 *
	 * <p>Mains rather than charging: a battery held at a charge limit reports
	 * "Not charging" while plugged in, which is this laptop's normal state all
	 * day. Green there would mean "draining", and it would be wrong every time
	 * the machine was on a cable.
	 *
	 * <p>Red is a warning to go and find a charger, so it is only for when
	 * there isn't one — low on mains is a battery that is already being dealt
	 * with.
	 */
	private static int colorFor(BatteryState battery) {
		DaemonConnection connection = MCShellClient.connection();
		if (connection != null && !connection.hud().batteryColor()) {
			// Pinned green by choice. The colours are information, but a HUD
			// that changes under you is a thing people are allowed to not
			// want, and green is the one the bar wears most of the time.
			return GREEN;
		}
		if (battery.mains() || battery.charging()) {
			return WHITE;
		}
		return battery.percent() < LOW ? RED : GREEN;
	}

	private static BatteryState state() {
		DaemonConnection connection = MCShellClient.connection();
		return connection == null ? null : connection.battery();
	}
}
