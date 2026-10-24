package dev.mcshell.screen;

import dev.mcshell.net.DaemonConnection;
import net.fabricmc.fabric.api.client.screen.v1.ScreenEvents;
import net.fabricmc.fabric.api.client.screen.v1.Screens;
import net.minecraft.client.MinecraftClient;
import net.minecraft.client.gui.screen.OpenToLanScreen;
import net.minecraft.client.gui.screen.Screen;
import net.minecraft.client.gui.screen.option.AccessibilityOptionsScreen;
import net.minecraft.client.gui.screen.option.ControlsOptionsScreen;
import net.minecraft.client.gui.screen.option.SoundOptionsScreen;
import net.minecraft.client.gui.screen.option.VideoOptionsScreen;
import net.minecraft.client.gui.widget.ButtonWidget;
import net.minecraft.text.Text;

/**
 * The lane switch: a button in the bottom-left of Minecraft's own options
 * screens that crosses to the machine's settings, and back again.
 *
 * <p>The machine's page is the one that opens. This is a desktop shell, so the
 * setting reached for is the machine's volume far more often than Minecraft's,
 * and the one you want should not be the one behind a button.
 *
 * <p>Minecraft's settings are not replaced, only moved one click away. Its
 * sound sliders still control Minecraft's sound, which is a different thing
 * from the machine's volume and a thing you still want — the shell being a
 * Minecraft world is the point.
 *
 * <p>Added through Fabric's screen events rather than a mixin. Adding a widget
 * to a vanilla screen is exactly what the event is for, and a mixin here would
 * be a maintenance cost with nothing to show for it.
 *
 * <p>A page appears here only once the daemon has a provider for it. Video and
 * Controls are one line each when they land.
 *
 * <p><b>Accessibility is the shell's own settings.</b> It is the last vanilla
 * options screen with nothing of ours behind it, and "what does this shell
 * draw, and what does it record" is the nearest thing the game has to that
 * subject. It crosses both ways like the other three: narrator, text
 * background and high-contrast are real settings for a real player, and this
 * world is played in.
 *
 * <p><b>Network is the one page with no lane back.</b> The pause menu's button
 * still says <i>Open to LAN</i>, which is deliberate: it is the vanilla wording
 * in the vanilla place, it is close enough to what the page is about that
 * nobody has to hunt for it, and a renamed button is one more tell that this is
 * not quite Minecraft. Open to LAN itself is not a thing this shell should do —
 * a desktop that can publish itself to the local network because someone
 * pressed a button in a settings menu is a surprise, not a feature. The other
 * three pages keep their button because Minecraft's own sound, video and keys
 * still matter; there is nothing on the other side of this one.
 *
 * <p>Which screen stands for a lane is not always vanilla's. A mod may replace
 * one outright — Sodium replaces the video screen — and the lane has to follow
 * it there, or the page it guards becomes unreachable.
 */
public final class SettingsIntegration {
	private SettingsIntegration() {
	}

	private static final int BUTTON_W = 120;
	private static final int BUTTON_H = 20;

	/**
	 * Set for exactly one opening, when the player asked for Minecraft's page.
	 *
	 * <p>Opening a vanilla options screen is otherwise redirected, and the
	 * button that crosses back opens that same screen — without this it would
	 * be bounced straight back to where it came from.
	 *
	 * <p>Client-thread only, like every screen transition.
	 */
	private static boolean wanted;

	/**
	 * Sodium's replacement for the video screen.
	 *
	 * <p>Matched by name rather than compiled against, because the alternative
	 * is a hard dependency on a mod that is not required to run, taken on to
	 * reach one class we only ever compare against. The check happens at
	 * runtime, so a Sodium that renames this costs the lane switch and nothing
	 * else. Sodium is pinned in {@code session/prism/mods.tsv}; if that pin
	 * moves and Video stops crossing over, this string is the first place to
	 * look.
	 *
	 * <p>Adding our widget to Sodium's screen is safe, which is not obvious and
	 * was checked rather than assumed: it extends {@code Screen}, delegates
	 * {@code addDrawableChild} straight up to it and calls {@code super.render},
	 * so a button added through Fabric's list draws and clicks like any other.
	 * Its one {@code clearChildren} sits inside {@code init()}, which runs
	 * before {@code AFTER_INIT} — so the button survives, and is put back on
	 * every resize the same way vanilla's is.
	 */
	private static final String SODIUM_VIDEO_SCREEN =
			"net.caffeinemc.mods.sodium.client.gui.VideoSettingsScreen";

	public static void register(DaemonConnection connection) {
		ScreenEvents.AFTER_INIT.register((client, screen, width, height) -> {
			String page = pageFor(screen);
			if (page == null) {
				return;
			}
			if (wanted) {
				wanted = false;
				addSwitch(connection, client, screen, height, page);
				return;
			}
			// Redirected after init rather than before it, so the screen we
			// hand over as the other lane is a fully built one that can simply
			// be shown again.
			client.setScreen(settingsFor(connection, screen, page));
		});
	}

	/** The daemon page that stands beside a Minecraft options screen, if any. */
	private static String pageFor(Screen screen) {
		if (screen instanceof SoundOptionsScreen) {
			return "audio";
		}
		if (screen instanceof VideoOptionsScreen || isSodiumVideo(screen)) {
			return "video";
		}
		if (screen instanceof ControlsOptionsScreen) {
			return "controls";
		}
		if (screen instanceof AccessibilityOptionsScreen) {
			return "general";
		}
		if (screen instanceof OpenToLanScreen) {
			return "network";
		}
		return null;
	}

	private static boolean isSodiumVideo(Screen screen) {
		return screen.getClass().getName().equals(SODIUM_VIDEO_SCREEN);
	}

	/** Show a Minecraft options screen, exempting it from the redirect once. */
	public static void showVanilla(MinecraftClient client, Screen vanilla) {
		wanted = true;
		client.setScreen(vanilla);
	}

	private static SettingsScreen settingsFor(DaemonConnection connection, Screen vanilla, String page) {
		boolean crossable = !page.equals("network");
		return new SettingsScreen(connection, page,
				Text.translatable("mcshell.settings.title." + page),
				crossable ? vanilla : null,
				crossable ? Text.translatable("mcshell.settings.minecraft." + page) : null);
	}

	private static void addSwitch(DaemonConnection connection, MinecraftClient client,
			Screen screen, int height, String page) {
		Text toSystem = Text.translatable("mcshell.settings.system." + page);
		Screens.getButtons(screen).add(ButtonWidget.builder(toSystem, button ->
						client.setScreen(settingsFor(connection, screen, page)))
				.dimensions(10, height - 26, BUTTON_W, BUTTON_H).build());
	}
}
